"""
KR 전종목 스캔 엔진

API 호출 전략 (US 버전과 차이):
  Stage 1 - KRX 일간 데이터로 거래량/시총/등락률 선필터 (API 호출 0)
  Stage 2 - 후보 종목 × 타임프레임별 키움 분봉 개별 조회 (ThreadPoolExecutor 5)
  Stage 3 - 캐시에서만 읽음 → 조건 평가 (API 호출 0)
"""
import time
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.ticker_provider import get_kr_tickers, get_ticker_info
from src.fetcher import get_ohlcv
from src.evaluator import evaluate

ROUND_INTERVAL = 60
PRELOAD_WORKERS = 5
MIN_CALL_INTERVAL = 0.15


def _put(q: Queue, msg: dict):
    q.put(msg)


# ── Stage 1: KRX 데이터 기반 선필터 (API 호출 없음) ─────────────

def _daily_filter(
    tickers: list[dict],
    logic: dict,
    q: Queue,
    stop_event: threading.Event,
) -> list[dict]:
    """KRX 일간 데이터로 거래량·시총·등락률 선필터 → 후보 리스트 반환"""
    vol_cond = next(
        (c for c in logic["conditions"]
         if c["type"] == "volume_range" and c.get("enabled", True)),
        None,
    )
    min_vol = int(vol_cond["min"]) if vol_cond else 100_000

    cap_cond = next(
        (c for c in logic["conditions"]
         if c["type"] == "market_cap_min_krw" and c.get("enabled", True)),
        None,
    )
    min_cap = float(cap_cond["min_krw"]) if cap_cond else 0

    rate_cond = next(
        (c for c in logic["conditions"]
         if c["type"] == "price_change_rate_min" and c.get("enabled", True)),
        None,
    )
    min_rate = float(rate_cond["value"]) if rate_cond else -999

    candidates = []
    total = len(tickers)

    for idx, t in enumerate(tickers):
        if stop_event.is_set():
            break
        if t["volume"] < min_vol:
            continue
        if t["market_cap"] < min_cap:
            continue
        if t["change_rate"] < min_rate:
            continue
        candidates.append(t)

        if idx % 200 == 0:
            _put(q, {
                "type": "progress",
                "phase": 1,
                "scanned": idx + 1,
                "total": total,
                "candidates": len(candidates),
                "msg": f"[1단계] 선필터 {idx+1:,}/{total:,} | 후보 {len(candidates):,}개",
            })

    _put(q, {
        "type": "progress",
        "phase": 1,
        "scanned": total,
        "total": total,
        "candidates": len(candidates),
        "msg": f"[1단계] 선필터 완료 | 후보 {len(candidates):,}/{total:,}",
    })
    return candidates


# ── Stage 2: 키움 분봉 프리로드 (ThreadPoolExecutor) ──────────

def _preload_timeframes(
    candidates: list[dict],
    intervals: set[str],
    q: Queue,
    stop_event: threading.Event,
):
    """후보 종목을 타임프레임별로 개별 조회 → fetcher 캐시에 저장"""
    tasks = [(t["code"], iv) for t in candidates for iv in intervals]
    total = len(tasks)
    if total == 0:
        return

    _put(q, {"type": "status", "msg": f"[2단계] {total:,}건 분봉 로드 시작..."})
    loaded = 0

    with ThreadPoolExecutor(max_workers=PRELOAD_WORKERS) as pool:
        futures = {pool.submit(get_ohlcv, code, iv): (code, iv) for code, iv in tasks}

        for f in as_completed(futures):
            if stop_event.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                return
            loaded += 1
            try:
                f.result()
            except Exception:
                pass

            if loaded % 20 == 0 or loaded == total:
                _put(q, {
                    "type": "progress",
                    "phase": 2,
                    "loaded": loaded,
                    "total": total,
                    "msg": f"[2단계] 분봉 로드 {loaded:,}/{total:,}",
                })


def _get_intervals_needed(logic: dict) -> set[str]:
    intervals = set()
    for c in logic["conditions"]:
        if c.get("enabled", True) and "interval" in c:
            intervals.add(c["interval"])
    intervals.discard("1d")
    return intervals


# ── 공통 ──────────────────────────────────────────────────────

def _wait_next_round(q: Queue, stop_event: threading.Event, round_num: int):
    for remaining in range(ROUND_INTERVAL, 0, -1):
        if stop_event.is_set():
            return
        _put(q, {
            "type": "countdown",
            "round": round_num,
            "remaining": remaining,
            "msg": f"R#{round_num} 완료 | 다음 스캔까지 {remaining}초",
        })
        time.sleep(1)
