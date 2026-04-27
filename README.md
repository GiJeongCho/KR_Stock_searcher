# KR Stock Screener

키움증권 REST API 기반 KOSPI/KOSDAQ 전종목 실시간 기술적 종목 검색기.

---

## 구현 현황

- [x] KOSPI + KOSDAQ 전종목 유니버스 (~2,600개)
- [x] 거래량 선필터 → 기술적 조건 평가 3단계 스캔
- [x] 한국 전용 조건: 등락률, 상한가 근접, 시총(원화)
- [x] 거래정지·관리종목 자동 제외
- [x] KOSPI / KOSDAQ 구분 필터 (UI)
- [x] 조건별 수치 웹 UI에서 직접 수정
- [x] KRX TradingView 차트 연동
- [x] 장 세션 표시 (정규장/장전/장후 등)
- [x] gunicorn / waitress 상시 구동 지원
- [ ] 텔레그램 알림

---

## 키움증권 REST API App Key 발급 방법

### 1단계: 키움증권 계좌 개설
키움증권 계좌가 없다면 먼저 개설하세요.  
- [키움증권 계좌 개설](https://www.kiwoom.com)

### 2단계: REST API 개발자 센터 접속
- [키움 REST API 개발자 센터](https://openapi.kiwoom.com)

### 3단계: 앱 등록 및 App Key 발급
1. 개발자 센터 → **앱 등록** 메뉴
2. 앱 이름, 설명 입력 후 등록
3. **App Key** 와 **App Secret** 발급 확인
4. 실전투자 API 신청 (승인 필요, 1~2 영업일 소요)

### 4단계: config/kiwoom.json 설정

```json
{
  "app_key": "발급받은_App_Key",
  "app_secret": "발급받은_App_Secret",
  "mock": false
}
```

> `"mock": true` 로 설정하면 모의투자 API (`mockapi.kiwoom.com`) 를 사용합니다.

---

## 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 개발 서버 (자동 리로드)
python app.py --reload

# 운영 서버 (waitress)
python app.py
```

접속: `http://localhost:4999`

---

## 디렉토리 구조

```
KR_Stock_searcher/
├── app.py                      # Flask 앱 · API 라우트 · 백그라운드 스캐너
├── requirements.txt
├── README.md
├── config/
│   ├── kiwoom.json             # App Key / App Secret (수동 설정 필요)
│   ├── logic1.json             # 급등이 조건 설정
│   ├── logic2.json             # 벌떡이 조건 설정
│   └── kr_tickers.json         # 종목 유니버스 캐시 (24h, 자동 생성)
├── src/
│   ├── auth.py                 # 키움 OAuth 토큰 발급·갱신
│   ├── ticker_provider.py      # KOSPI/KOSDAQ 전종목 수집
│   ├── fetcher.py              # 키움 REST API 래퍼 · 인터벌별 캐시
│   ├── indicators.py           # SMA · 볼린저밴드 · 엔벨로프
│   ├── evaluator.py            # 조건 평가 (한국 전용 조건 포함)
│   └── scanner.py              # 배치 스캔 엔진 (ThreadPoolExecutor)
├── templates/
│   ├── index.html              # 메인 웹 UI
│   └── login.html              # 로그인/회원가입
└── data/
    └── users.db                # 사용자 DB (자동 생성)
```

---

## 검색기 로직

### 급등이 (`config/logic1.json`)

| # | 조건 | 파라미터 |
|---|------|----------|
| 1 | 일봉 거래량 | 100,000 이상 |
| 2 | 시가총액 | 500억 이상 |
| 3 | 전일 대비 등락률 | +3% 이상 |
| 4 | 5분봉 이평배열 | MA5 ≥ MA20 ≥ MA60 |
| 5 | 5분봉 이평배열 | MA5 ≥ MA20 ≥ MA120 |
| 6 | 5분봉 볼린저밴드 상향돌파 | 기간 20, 표준편차 2.0 |
| 7 | 5분봉 엔벨로프 상향돌파 | 기간 12, 2.2% |
| 8 | 60분봉 이평배열 | MA5 ≥ MA20 ≥ MA60 |

### 벌떡이 (`config/logic2.json`)

| # | 조건 | 파라미터 |
|---|------|----------|
| 1 | 일봉 거래량 | 50,000 이상 |
| 2 | 시가총액 | 300억 이상 |
| 3 | 전일 대비 등락률 | +1% 이상 |
| 4 | 1분봉 이평배열 | MA5 ≥ MA60 ≥ MA120 |
| 5 | 1분봉 이평배열 | MA5 ≥ MA120 ≥ MA240 |
| 6 | 5분봉 이평배열 | MA5 ≥ MA20 ≥ MA60 |
| 7 | 5분봉 이평이격도 MA5-MA120 | 10% 이내 |
| 8 | 15분봉 이평배열 | MA5 ≥ MA20 ≥ MA60 |
| 9 | 1분봉 엔벨로프 상향돌파 | 기간 12, 2.0% |
| 10 | 5분봉 엔벨로프 상향돌파 | 기간 12, 3.0% |

> 모든 수치는 웹 UI 왼쪽 패널에서 실시간 수정 후 저장 가능.

---

## 지원 조건 타입

| type | 설명 |
|------|------|
| `ma_alignment` | MA_a ≥ MA_b ≥ MA_c 정배열 |
| `ma_compare` | MA_fast ≥ MA_slow |
| `ma_gap` | \|MA_fast − MA_slow\| / MA_slow ≤ N% |
| `bb_breakout` | 볼린저밴드 상한선 상향돌파 |
| `bb_above` | 볼린저밴드 상한선 이상 |
| `envelope_breakout` | 엔벨로프 상한선 상향돌파 |
| `volume_range` | 거래량 min ~ max |
| `market_cap_min_krw` | 시가총액 ≥ N원 |
| `price_change_rate_min` | 전일 대비 등락률 ≥ N% |
| `upper_limit_proximity` | 상한가(+30%) 근접 N% 이내 |
| `market_filter` | KOSPI / KOSDAQ 구분 |

---

## API 호출 전략

```
Stage 1 │ ThreadPoolExecutor(5) · 일봉 ka10082 개별 조회 → 거래량 선필터
        │ ~2,600종목 / 약 1~2분
        ↓
Stage 2 │ ThreadPoolExecutor(5) · 분봉 ka10080 개별 조회 → fetcher 캐시 주입
        │ 후보(수백개) × 인터벌 수 / 약 1~2분
        ↓
Stage 3 │ 캐시에서만 읽음 → 조건 평가 (API 호출 0)
        │ 약 30초
```

| 항목 | 값 |
|------|-----|
| Stage1 워커 수 | 5 |
| Stage2 워커 수 | 5 |
| 호출 간 최소 간격 | 0.15초/스레드 |
| 개별 캐시 TTL | 1m=30s / 5m=2m / 15m=5m / 60m=10m / 1d=10m |

---

## 의존성 설치

```bash
pip install flask flask-login sqlalchemy bcrypt waitress requests pandas numpy
```

---

## 주의사항

- **키움증권 REST API**는 App Key / App Secret 발급 필수
- 한국 정규장 시간: **09:00 ~ 15:30 KST** (장 외 시간에는 분봉 데이터 미갱신)
- `config/kiwoom.json` 을 `.gitignore` 에 추가하여 키 노출 방지 권장
