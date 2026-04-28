"""종목 + 로직 조건 평가기 (US 구조 동일 + 한국 전용 조건)"""
from src.fetcher import get_ohlcv
from src.ticker_provider import get_ticker_info
from src import indicators as ind


def _eval_condition(cond: dict, code: str, df_cache: dict, info: dict) -> dict:
    """단일 조건 평가 → {id, label, pass, reason}"""
    cid = cond["id"]
    label = cond["label"]
    enabled = cond.get("enabled", True)

    if not enabled:
        return {"id": cid, "label": label, "pass": None, "reason": "비활성화"}

    ctype = cond["type"]
    result = False
    reason = ""

    try:
        interval = cond.get("interval")

        def get_df(iv):
            if iv not in df_cache:
                df_cache[iv] = get_ohlcv(code, iv)
            return df_cache[iv]

        if ctype == "ma_alignment":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_ma_alignment(df, cond["periods"])

        elif ctype == "bb_breakout":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_bb_breakout(df, cond["period"], cond["std"])

        elif ctype == "bb_above":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_bb_above(df, cond["period"], cond["std"])

        elif ctype == "envelope_breakout":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_envelope_breakout(df, cond["period"], cond["pct"])

        elif ctype == "ma_gap":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_ma_gap(df, cond["fast"], cond["slow"], cond["threshold_pct"])

        elif ctype == "ma_compare":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_ma_compare(df, cond["fast"], cond["slow"])

        elif ctype == "volume_range":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_volume_range(df, cond["min"], cond["max"])

        elif ctype == "bb_upper_only":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_bb_upper_only(df, cond["period"], cond["std"])

        elif ctype == "price_ma_offset":
            df = get_df(interval)
            if df is None:
                reason = "데이터 없음"
            else:
                result = ind.check_price_ma_offset(df, cond["period"], cond.get("offset_pct", 0))

        # ── 한국 전용 (KRX 데이터 기반) ───────────────────────
        elif ctype == "market_cap_min_krw":
            result = ind.check_market_cap_krw(info, cond["min_krw"])

        elif ctype == "price_change_rate_min":
            result = ind.check_price_change_rate(info, cond["value"])

        elif ctype == "upper_limit_proximity":
            result = ind.check_upper_limit_proximity(info, cond.get("pct", 5))

        elif ctype == "market_filter":
            result = ind.check_market_filter(info, cond.get("market", ""))

        else:
            reason = f"알 수 없는 조건 타입: {ctype}"

    except Exception as e:
        reason = f"오류: {e}"

    return {"id": cid, "label": label, "pass": result, "reason": reason}


_INFO_COND_TYPES = {
    "market_cap_min_krw", "price_change_rate_min",
    "upper_limit_proximity", "market_filter",
}


def evaluate(code: str, logic: dict) -> dict:
    """
    code 에 대해 logic 전체 조건 평가.
    OHLCV 조건을 먼저 평가하고, KRX 데이터 조건은 별도로 처리.
    """
    df_cache: dict = {}
    conditions = logic.get("conditions", [])

    ohlcv_conds = [c for c in conditions if c["type"] not in _INFO_COND_TYPES]
    info_conds = [c for c in conditions if c["type"] in _INFO_COND_TYPES]

    results = []
    for cond in ohlcv_conds:
        r = _eval_condition(cond, code, df_cache, {})
        results.append(r)

    ohlcv_enabled = [r for r in results if r["pass"] is not None]
    ohlcv_all_pass = all(r["pass"] for r in ohlcv_enabled) if ohlcv_enabled else True

    info = get_ticker_info(code) if (ohlcv_all_pass and info_conds) else {}

    for cond in info_conds:
        r = _eval_condition(cond, code, df_cache, info)
        results.append(r)

    enabled_results = [r for r in results if r["pass"] is not None]
    all_pass = all(r["pass"] for r in enabled_results) if enabled_results else False

    ticker_info = get_ticker_info(code)
    return {
        "ticker": code,
        "ticker_name": ticker_info.get("name", ""),
        "logic_name": logic.get("name", ""),
        "conditions": results,
        "all_pass": all_pass,
        "pass_count": sum(1 for r in enabled_results if r["pass"]),
        "total_count": len(enabled_results),
    }
