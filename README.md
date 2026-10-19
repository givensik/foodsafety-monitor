# 식품안전나라 실시간 인허가 모니터링 대시보드 (`foodsafety-monitor`)

식품의약품안전처(식품안전나라)의 신규 인허가 업소 현황을 실시간으로 모니터링하고, 식약처 OpenAPI(`I2500`) 및 상세 대장 팝업(`bsnInfoDetail.do`)과 연동하여 **실제 인허가일자(`PRMS_DT`)**, **16자리 대장번호(`BSN_LCNS_LEDG_NO`) `+1` 채번 검증**, **가등록(상호·주소 반영 대기중) 상태 추적**을 제공하는 대시보드입니다.

- **운영 도메인**: [https://store.givensik.space](https://store.givensik.space)
- **기본 Pages URL**: [https://foodsafety-monitor.pages.dev](https://foodsafety-monitor.pages.dev)
- **식약처 홈페이지 & OpenAPI 실데이터 검증 문서**: [docs/FOODSAFETY_API_GUIDE.md](docs/FOODSAFETY_API_GUIDE.md)

---

## 1. 주요 기능

1. **상단 식약처 DB 실시간 업데이트 현황판**:
   - **지역별 총 등록 업소 수(`totCnt`)**: `searchBsnListCnt.do` 기준 실시간 등록 건수 표시
   - **조회 목록 최고 대장번호(`BSN_LCNS_LEDG_NO`, 16자리)**: 전국 통합 시퀀스 최신 번호 표시
   - **오늘 자 OpenAPI(`I2500`) 당일 변경 건수(`CHNG_DT=오늘`) 및 19시 개방 상태**: 19시 이전 `INFO-700` 잠금 대기 여부 및 19시 이후 당일 누적 변경 건수(예: 20시 배치 `1,963건`) 실시간 표시
2. **16자리 대장번호 & `+1` 다음 번호 즉시 검증기 (`/api/ledger`)**:
   - 특정 16자리 대장번호나 현재 최고 대장번호의 `+1` 번호를 즉시 조회하여 식약처 DB(`bsnInfoDetail.do`)에 새 번호가 생성되었는지 실시간으로 확인
3. **가등록(상호·주소 공란) 신규 채번 레코드 자동 구분 및 갱신**:
   - 번호·업종·대표자·허가일은 생성되었으나 상호명(`BSSH_NM`)과 주소(`SITE_ADDR`)가 아직 빈칸(`""`)인 초기 동기화 레코드를 **`신규 채번 (상호·주소 반영 대기중)`** 배지로 구분해 표시하고, 추후 상호명이 반영되면 자동으로 갱신
4. **실데이터 기반 식약처 번호 체계 및 배치 검증 리포트 내장**:
   - 11자리 인허가번호(`LCNS_NO`) vs 16자리 대장번호(`BSN_LCNS_LEDG_NO`) 채번 규칙, `s_order_by` 화이트리스트 검증 결과, 19:00/20:00 배치 타임라인을 대시보드 하단 접이식 리포트 패널로 제공

---

## 2. 디렉토리 구조

```text
foodsafety-monitor/
├── public/
│   └── index.html               # 프론트엔드 대시보드 UI (현황판 + 대장번호 +1 검증기 + CSV 다운로드)
├── functions/
│   └── api/
│       ├── businesses.js        # 실시간 목록, 총 건수(totCnt), OpenAPI(I2500) 상태 및 허가일 조회 API
│       └── ledger.js            # 16자리 대장번호(bsn_lcns_ledg_no) 단건 및 +1 생성 여부 즉시 검증 API
├── docs/
│   └── FOODSAFETY_API_GUIDE.md  # 식약처 포털 내부 동작 원리 & OpenAPI 실데이터 검증 문서
├── data/                        # 파이썬 수집기 로컬 저장 데이터 (JSON / CSV)
├── monitor_new_businesses.py    # 파이썬 기반 단독 수집 스크립트
├── GEMINI.md                    # 추측 금지 및 실데이터 검증 원칙 (No-Speculation Rule)
├── wrangler.toml                # Cloudflare Pages & KV(DETECTED_STORES) 설정
└── package.json                 # 로컬 실행 및 배포 스크립트
```

---

## 3. 다른 PC에서 클론 후 로컬 실행 방법 (`http://localhost:8788`)

Node.js(v18 이상)만 설치되어 있으면 별도 설정 없이 프론트엔드(`public/index.html`), 백엔드 API(`functions/api/businesses.js`, `functions/api/ledger.js`), 로컬 에뮬레이션 KV(`DETECTED_STORES`)가 모두 로컬에서 동일하게 작동합니다.

```bash
git clone https://github.com/givensik/foodsafety-monitor.git
cd foodsafety-monitor
npm run dev
```

- 실행 후 브라우저에서 **`http://localhost:8788`** 접속
- 로컬 실행 시에는 Cloudflare 로그인 없이도 로컬 KV(`.wrangler/state`)를 사용하여 즉시 동작합니다.

---

## 4. 수정 후 실서버(`store.givensik.space`) 배포 방법

다른 PC에서 코드를 수정한 뒤 실서버에 반영하려면 최초 1회 Cloudflare 로그인 후 배포 명령어를 실행합니다.

```bash
npx wrangler@3 login   # 최초 1회 브라우저 로그인
npm run deploy         # store.givensik.space 에 즉시 반영
```

---

## 5. 파이썬 로컬 단독 수집 스크립트 실행 (선택)

웹 대시보드와 별개로 로컬 PC에 CSV 파일로 데이터를 수집하고 싶을 때 실행합니다.

```bash
python3 monitor_new_businesses.py check --sido seoul
```
