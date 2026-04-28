"""키움 REST API OAuth 토큰 관리.

- 발급: POST /oauth2/token
- 응답: {expires_dt: 'YYYYMMDDHHMMSS', token_type: 'bearer', token: '...', return_code: 0, ...}
- 만료 60초 전부터는 자동 재발급.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests


REAL_HOST = "https://api.kiwoom.com"
MOCK_HOST = "https://mockapi.kiwoom.com"

_REFRESH_MARGIN = timedelta(seconds=60)


@dataclass
class KiwoomConfig:
    app_key: str
    app_secret: str
    mock: bool = False

    @property
    def host(self) -> str:
        return MOCK_HOST if self.mock else REAL_HOST

    @classmethod
    def load(cls, path: str | Path = "config/kiwoom.json") -> "KiwoomConfig":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"{p} 가 없습니다. config/kiwoom.example.json 을 복사해서 키를 입력하세요."
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            app_key=data["app_key"],
            app_secret=data["app_secret"],
            mock=bool(data.get("mock", False)),
        )


class TokenManager:
    """접근 토큰 발급·캐싱.

    스레드 안전: 동시에 여러 워커가 token() 을 호출해도 락으로 1회만 발급.
    """

    def __init__(self, config: KiwoomConfig, timeout: float = 10.0):
        self.config = config
        self.timeout = timeout
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._lock = threading.Lock()

    @property
    def host(self) -> str:
        return self.config.host

    def token(self) -> str:
        """유효한 접근 토큰 반환. 필요시 재발급."""
        with self._lock:
            if self._token and self._expires_at and datetime.now() < self._expires_at - _REFRESH_MARGIN:
                return self._token
            self._issue()
            assert self._token is not None
            return self._token

    def _issue(self) -> None:
        url = f"{self.host}/oauth2/token"
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "secretkey": self.config.app_secret,
        }
        res = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        res.raise_for_status()
        data = res.json()

        if data.get("return_code") != 0:
            raise RuntimeError(
                f"토큰 발급 실패: code={data.get('return_code')} msg={data.get('return_msg')}"
            )

        self._token = data["token"]
        self._expires_at = datetime.strptime(data["expires_dt"], "%Y%m%d%H%M%S")

    def revoke(self) -> None:
        """접근 토큰 폐기."""
        if not self._token:
            return
        url = f"{self.host}/oauth2/revoke"
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        body = {
            "appkey": self.config.app_key,
            "secretkey": self.config.app_secret,
            "token": self._token,
        }
        try:
            requests.post(url, headers=headers, json=body, timeout=self.timeout)
        finally:
            self._token = None
            self._expires_at = None
