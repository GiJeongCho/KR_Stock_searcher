"""
KOSPI + KOSDAQ 전종목 리스트 제공
소스: 네이버 금융 모바일 API (안정적, 실시간 시세 포함)
캐시: config/kr_tickers.json (24h TTL)
"""
import os
import json
import time
import logging

import requests

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "kr_tickers.json")
CACHE_TTL = 86400  # 24시간

NAVER_API = "https://m.stock.naver.com/api/stocks/marketValue"
PAGE_SIZE = 100
_HEADERS = {"User-Agent": "Mozilla/5.0"}

_ticker_data: dict[str, dict] = {}


def _parse_num(val, default=0):
    if val is None:
        return default
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return default


def get_kr_tickers() -> list[dict]:
    """
    전종목 리스트 반환 (캐시 우선, 24h 갱신)
    각 항목: {code, name, market, close, change_rate, volume, market_cap, listed_shares}
    """
    global _ticker_data

    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) < CACHE_TTL:
            tickers = data["tickers"]
            _ticker_data = {t["code"]: t for t in tickers}
            return tickers

    tickers = _fetch_with_fallback()

    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "tickers": tickers}, f, ensure_ascii=False)

    _ticker_data = {t["code"]: t for t in tickers}
    return tickers


def _fetch_with_fallback() -> list[dict]:
    """네이버 → 만료 캐시 순으로 시도"""
    try:
        print("[ticker_provider] 네이버 금융에서 종목 리스트 다운로드 중...")
        tickers = _fetch_naver()
        if tickers:
            print(f"[ticker_provider] 네이버: {len(tickers)}개 종목 로드 완료")
            return tickers
    except Exception as e:
        print(f"[ticker_provider] 네이버 실패: {e}")

    if os.path.exists(CACHE_FILE):
        print("[ticker_provider] 소스 실패, 만료 캐시 사용")
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("tickers", [])

    raise RuntimeError("종목 리스트를 가져올 수 없습니다")


def _fetch_naver() -> list[dict]:
    tickers = []
    for market in ("KOSPI", "KOSDAQ"):
        page = 1
        while True:
            url = f"{NAVER_API}/{market}?page={page}&pageSize={PAGE_SIZE}"
            res = requests.get(url, headers=_HEADERS, timeout=15)
            res.raise_for_status()
            data = res.json()

            stocks = data.get("stocks", [])
            if not stocks:
                break

            for s in stocks:
                code = s.get("itemCode", "").strip()
                if not code or len(code) != 6 or not code.isdigit():
                    continue

                tickers.append({
                    "code": code,
                    "name": s.get("stockName", "").strip(),
                    "market": market,
                    "close": _parse_num(s.get("closePriceRaw", s.get("closePrice"))),
                    "change_rate": _parse_num(s.get("fluctuationsRatio")),
                    "volume": _parse_num(s.get("accumulatedTradingVolumeRaw", s.get("accumulatedTradingVolume"))),
                    "market_cap": _parse_num(s.get("marketValueRaw", s.get("marketValue"))) ,
                    "listed_shares": 0,
                })

            total = data.get("totalCount", 0)
            if page * PAGE_SIZE >= total:
                break
            page += 1
            time.sleep(0.1)

    return tickers


def get_ticker_info(code: str) -> dict:
    """종목 코드로 데이터 조회 (캐시 기반)"""
    if not _ticker_data:
        get_kr_tickers()
    return _ticker_data.get(code, {})


def force_refresh() -> list[dict]:
    """캐시 무시하고 강제 갱신"""
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    return get_kr_tickers()


def get_ticker_count() -> dict:
    """캐시 상태 반환"""
    if not os.path.exists(CACHE_FILE):
        return {"cached": False, "count": 0}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    age_hours = (time.time() - data.get("ts", 0)) / 3600
    return {
        "cached": True,
        "count": len(data.get("tickers", [])),
        "age_hours": round(age_hours, 1),
        "stale": age_hours > 24,
    }
