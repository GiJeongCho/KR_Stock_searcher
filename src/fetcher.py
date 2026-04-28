"""키움 REST API 시세 래퍼 (skeleton).

검증 단계: 일봉 ka10082 단일 종목 호출만 구현.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .auth import TokenManager


CHART_PATH = "/api/dostk/chart"


class KiwoomFetcher:
    def __init__(self, tokens: TokenManager, timeout: float = 10.0):
        self.tokens = tokens
        self.timeout = timeout

    def _post(self, path: str, api_id: str, body: dict, *, cont_yn: str = "N", next_key: str = "") -> dict:
        url = f"{self.tokens.host}{path}"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.tokens.token()}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": api_id,
        }
        res = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        res.raise_for_status()
        data = res.json()
        if data.get("return_code") not in (0, None):
            raise RuntimeError(
                f"{api_id} 실패: code={data.get('return_code')} msg={data.get('return_msg')}"
            )
        return data

    def daily_candles(
        self,
        stk_cd: str,
        base_dt: str | None = None,
        upd_stkpc_tp: str = "1",
    ) -> dict[str, Any]:
        """주식일봉차트조회 (ka10082).

        Args:
            stk_cd: 종목코드 (6자리, 예: "005930")
            base_dt: 기준일자 YYYYMMDD. None 이면 오늘.
            upd_stkpc_tp: 수정주가구분 ("0":미적용, "1":적용)
        """
        body = {
            "stk_cd": stk_cd,
            "base_dt": base_dt or datetime.now().strftime("%Y%m%d"),
            "upd_stkpc_tp": upd_stkpc_tp,
        }
        return self._post(CHART_PATH, "ka10082", body)
