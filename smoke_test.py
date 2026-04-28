"""검증용 스모크 테스트.

1) 키움 OAuth 토큰 발급 확인
2) 삼성전자(005930) 일봉 ka10082 호출 → 최근 5개 캔들 출력

실행:
    cd KR_Stock_searcher
    python smoke_test.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.auth import KiwoomConfig, TokenManager
from src.fetcher import KiwoomFetcher


def main() -> int:
    config = KiwoomConfig.load("config/kiwoom.json")
    print(f"[cfg] mock={config.mock} host={config.host}")

    tokens = TokenManager(config)

    print("[1/2] OAuth 토큰 발급 시도...")
    token = tokens.token()
    print(f"      token  = {token[:24]}...")
    print(f"      expire = {tokens._expires_at}")

    print("[2/2] 일봉 ka10082 호출 (005930 삼성전자)...")
    fetcher = KiwoomFetcher(tokens)
    data = fetcher.daily_candles("005930")

    print(f"      return_code = {data.get('return_code')}")
    print(f"      return_msg  = {data.get('return_msg')}")
    print(f"      top-level keys = {list(data.keys())}")

    candles = None
    for key, val in data.items():
        if isinstance(val, list) and val:
            candles = val
            print(f"      [{key}] 길이 = {len(val)}")
            break

    if candles:
        print("      ▶ 최근 5개 캔들 (raw):")
        print(json.dumps(candles[:5], ensure_ascii=False, indent=2))
    else:
        print("      ! 캔들 배열을 못 찾았습니다. 전체 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))

    print("\n[OK] 스모크 테스트 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
