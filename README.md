# 식품안전나라 실시간 인허가 모니터링 대시보드 (`foodsafety-monitor`)

식품의약품안전처(식품안전나라)의 신규 인허가 업소 현황을 실시간으로 모니터링하고, 식약처 OpenAPI(`I2500`)와 연동하여 **실제 구청 인허가일자(`PRMS_DT`)** 및 **최초 감지시각**을 제공하는 대시보드입니다.

- **운영 도메인**: [https://store.givensik.space](https://store.givensik.space)
- **기본 Pages URL**: [https://foodsafety-monitor.pages.dev](https://foodsafety-monitor.pages.dev)
- **식약처 홈페이지 & OpenAPI 기술 분석 문서**: [docs/FOODSAFETY_API_GUIDE.md](docs/FOODSAFETY_API_GUIDE.md)

---

## 1. 디렉토리 구조

```text
foodsafety-monitor/
├── public/
│   └── index.html               # 프론트엔드 대시보드 UI (TailwindCSS + CSV 다운로드)
├── functions/
│   └── api/
│       └── businesses.js        # Cloudflare Pages Function (/api/businesses 백엔드 API)
├── docs/
│   └── FOODSAFETY_API_GUIDE.md  # 식약처 포털 내부 동작 원리 & OpenAPI 데이터 명세서
├── data/                        # 파이썬 수집기 로컬 저장 데이터 (JSON / CSV)
├── monitor_new_businesses.py    # 파이썬 기반 단독 수집 스크립트
├── wrangler.toml                # Cloudflare Pages & KV(DETECTED_STORES) 설정
└── package.json                 # 로컬 실행 및 배포 스크립트
```

---

## 2. 다른 PC에서 클론 후 로컬 실행 방법 (`http://localhost:8788`)

Node.js(v18 이상)만 설치되어 있으면 별도 설정 없이 프론트엔드(`public/index.html`), 백엔드 API(`functions/api/businesses.js`), 로컬 에뮬레이션 KV(`DETECTED_STORES`)가 모두 로컬에서 동일하게 작동합니다.

```bash
git clone https://github.com/givensik/foodsafety-monitor.git
cd foodsafety-monitor
npm run dev
```

- 실행 후 브라우저에서 **`http://localhost:8788`** 접속
- 로컬 실행 시에는 Cloudflare 로그인 없이도 로컬 KV(`.wrangler/state`)를 사용하여 즉시 동작합니다.

---

## 3. 수정 후 실서버(`store.givensik.space`) 배포 방법

다른 PC에서 코드를 수정한 뒤 실서버에 반영하려면 최초 1회 Cloudflare 로그인 후 배포 명령어를 실행합니다.

```bash
npx wrangler@3 login   # 최초 1회 브라우저 로그인
npm run deploy         # store.givensik.space 에 즉시 반영
```

---

## 4. 파이썬 로컬 단독 수집 스크립트 실행 (선택)

웹 대시보드와 별개로 로컬 PC에 JSON/CSV 파일로 데이터를 수집하고 싶을 때 실행합니다.

```bash
python3 monitor_new_businesses.py --once
```
- 실행 결과는 `data/new_businesses.json`, `data/new_businesses.csv` 에 저장됩니다.
