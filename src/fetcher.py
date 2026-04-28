"""
키움 REST API 시세 fetcher — 캐싱 + 스레드 안전 Rate Limit

일봉: ka10082 / 분봉: ka10080 → pandas DataFrame (Open, High, Low, Close, Volume)
"""
import time
import logging
import threading
from datetime import datetime

import pandas as pd
import requests

from .auth import KiwoomConfig, TokenManager

CHART_PATH = "/api/dostk/chart"

CACHE_TTL = {
    "1m":  30,
    "5m":  120,
    "15m": 300,
    "60m": 600,
    "1d":  600,
}

TIC_SCOPE_MAP = {"1m": "1", "5m": "5", "15m": "15", "60m": "60"}

MIN_CALL_INTERVAL = 0.3
_MAX_RETRIES = 3
_BACKOFF_BASE = 5

OHLCV_FIELD_CANDIDATES = {
    "Open":   ["strt_prc", "open_prc", "oprc", "open"],
    "High":   ["high_prc", "hprc", "high"],
    "Low":    ["low_prc", "lprc", "low"],
    "Close":  ["clos_prc", "cur_prc", "cprc", "close", "clpr", "stck_clpr"],
    "Volume": ["trde_qty", "tvol", "volume", "acml_vol", "acml_tr_pbmn"],
}
DATE_FIELDS = ["stk_dt", "dt", "trd_dt", "date", "stck_bsop_date"]
TIME_FIELDS = ["stk_tm", "tm", "time", "stck_cntg_hour"]


class _KiwoomFetcher:
    def __init__(self):
        config = KiwoomConfig.load()
        self.tokens = TokenManager(config)
        self._cache: dict = {}
        self._cache_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._last_call_time = 0.0
        self._timeout = 10.0
        self._field_map: dict | None = None

    def _rate_limit(self):
        with self._call_lock:
            now = time.time()
            wait = MIN_CALL_INTERVAL - (now - self._last_call_time)
            if wait > 0:
                time.sleep(wait)
            self._last_call_time = time.time()

    def _post(self, api_id: str, body: dict,
              cont_yn: str = "N", next_key: str = "") -> tuple[dict, str]:
        self._rate_limit()
        url = f"{self.tokens.host}{CHART_PATH}"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.tokens.token()}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": api_id,
        }
        res = requests.post(url, headers=headers, json=body, timeout=self._timeout)
        res.raise_for_status()
        return res.json(), res.headers.get("next-key", "")

    # ── public API ────────────────────────────────────────────

    def get_ohlcv(self, code: str, interval: str) -> pd.DataFrame | None:
        key = (code, interval)
        ttl = CACHE_TTL.get(interval, 120)

        with self._cache_lock:
            if key in self._cache:
                ts, df = self._cache[key]
                if time.time() - ts < ttl:
                    return df

        for attempt in range(_MAX_RETRIES):
            try:
                if interval == "1d":
                    df = self._fetch_daily(code)
                else:
                    tic = TIC_SCOPE_MAP.get(interval)
                    if not tic:
                        return None
                    df = self._fetch_minute(code, tic)

                if df is not None and not df.empty:
                    with self._cache_lock:
                        self._cache[key] = (time.time(), df)
                return df
            except Exception as e:
                err = str(e).lower()
                if "429" in err or "rate" in err or "too many" in err:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logging.warning(
                        f"[fetcher] {code} {interval} Rate Limited → {wait}초 대기 ({attempt+1}/{_MAX_RETRIES})"
                    )
                    time.sleep(wait)
                else:
                    logging.warning(
                        f"[fetcher] {code} {interval} 오류 ({attempt+1}/{_MAX_RETRIES}): {e}"
                    )
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(1)
        return None

    # ── internal ──────────────────────────────────────────────

    def _fetch_daily(self, code: str) -> pd.DataFrame | None:
        body = {
            "stk_cd": code,
            "base_dt": datetime.now().strftime("%Y%m%d"),
            "upd_stkpc_tp": "1",
        }
        data, _ = self._post("ka10082", body)
        return self._parse_candles(data)

    def _fetch_minute(self, code: str, tic_scope: str,
                      max_candles: int = 300) -> pd.DataFrame | None:
        body = {"stk_cd": code, "tic_scope": tic_scope}
        all_candles: list[dict] = []
        next_key = ""

        for _ in range(5):
            cont_yn = "N" if not next_key else "Y"
            data, next_key = self._post("ka10080", body, cont_yn, next_key)

            chunk = self._extract_array(data)
            if not chunk:
                break
            all_candles.extend(chunk)
            if len(all_candles) >= max_candles or not next_key:
                break

        return self._candles_to_df(all_candles) if all_candles else None

    @staticmethod
    def _extract_array(data) -> list[dict]:
        if isinstance(data, list):
            return data
        for val in data.values():
            if isinstance(val, list) and val:
                return val
        return []

    def _parse_candles(self, data) -> pd.DataFrame | None:
        candles = self._extract_array(data)
        return self._candles_to_df(candles) if candles else None

    def _detect_fields(self, sample: dict):
        mapping: dict[str, str] = {}
        for std, candidates in OHLCV_FIELD_CANDIDATES.items():
            for c in candidates:
                if c in sample:
                    mapping[c] = std
                    break
        self._field_map = mapping

    def _candles_to_df(self, candles: list[dict]) -> pd.DataFrame | None:
        if not candles:
            return None

        if self._field_map is None:
            self._detect_fields(candles[0])
        fmap = self._field_map or {}

        records = []
        for c in candles:
            row: dict = {}
            for orig, std in fmap.items():
                val = c.get(orig)
                if val is not None:
                    try:
                        row[std] = float(str(val).replace(",", ""))
                    except (ValueError, TypeError):
                        row[std] = 0.0

            dt_str = None
            for f in DATE_FIELDS:
                if f in c:
                    dt_str = str(c[f])
                    break
            tm_str = None
            for f in TIME_FIELDS:
                if f in c:
                    tm_str = str(c[f])
                    break
            if dt_str:
                try:
                    ts = f"{dt_str} {tm_str}" if tm_str else dt_str
                    row["datetime"] = pd.Timestamp(ts)
                except Exception:
                    pass

            records.append(row)

        df = pd.DataFrame(records)
        if "datetime" in df.columns:
            df = df.sort_values("datetime").reset_index(drop=True)

        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col not in df.columns:
                return None
        return df


# ── module-level singleton ─────────────────────────────────

_fetcher: _KiwoomFetcher | None = None
_init_lock = threading.Lock()


def _ensure_init() -> _KiwoomFetcher:
    global _fetcher
    if _fetcher is None:
        with _init_lock:
            if _fetcher is None:
                _fetcher = _KiwoomFetcher()
    return _fetcher


def get_ohlcv(code: str, interval: str) -> pd.DataFrame | None:
    return _ensure_init().get_ohlcv(code, interval)


def get_cache():
    f = _ensure_init()
    return f._cache, f._cache_lock


def clear_cache(code: str | None = None):
    f = _ensure_init()
    with f._cache_lock:
        if code is None:
            f._cache.clear()
        else:
            for k in [k for k in f._cache if k[0] == code]:
                del f._cache[k]
