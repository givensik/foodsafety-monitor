# 네이버 지도 크롬 프로필(`naver_map_profile/`) 관리 안내

Google Drive `baemin/naver_map_profile/` 에 보관 중인 폴더는 **크롬(Chromium) 브라우저 사용자 프로필**이다.
로그인 세션이 들어 있을 수 있으므로 **이 레포에는 올리지 않고** `.gitignore` 로 제외한다.

## 1. Drive 폴더 구성 (2026-11-04 확인)

[확인된 팩트] Drive API로 목록을 조회한 결과:

```text
baemin/
└── naver_map_profile/
    ├── Default/               # 사용자 데이터 (Cache, AutofillStrikeDatabase, AutofillAiModelCache, BudgetDatabase, blob_storage ...)
    ├── BrowserMetrics/
    ├── component_crx_cache/
    ├── Crashpad/
    ├── Local State            # 13,815 bytes
    ├── Last Browser / Last Version
    ├── Variations / VariationsSeedV2 / VariationsSafeSeedV2
    ├── CrashpadMetrics-active.pma   # 1 MB
    └── ko-3-0.bdic            # 11 MB, 한국어 맞춤법 사전
```

[미검증 가설 — 테스트 필요] `Default/` 하위의 `Cookies`, `Login Data`, `Local Storage` 파일 존재 여부와 실제 로그인 세션 포함 여부는 아직 직접 열어 확인하지 않았다.
크롬 프로필 구조상 포함될 수 있는 파일이므로, 확인 전까지는 **포함되어 있다고 가정하고** 공개 저장소에 올리지 않는다.

## 2. 레포에 올리지 않는 이유

| 이유 | 예시 |
|---|---|
| 세션 탈취 위험 | 프로필 폴더를 받은 사람이 크롬에 지정하면 비밀번호 입력 없이 로그인된 상태로 열릴 수 있음 |
| git 기록에 영구 보존 | 나중에 파일을 지워도 과거 커밋에서 복원 가능 |
| 코드와 무관한 바이너리 | 캐시·사전 파일이 대부분이라 레포 용량만 증가 |

## 3. 로컬에서 사용하는 방법

1. Drive에서 `naver_map_profile/` 폴더를 내려받아 레포 루트(또는 원하는 경로)에 둔다. `.gitignore` 에 등록되어 있어 `git add .` 해도 올라가지 않는다.
2. Playwright 예시:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context("naver_map_profile", headless=False)
    page = ctx.new_page()
    page.goto("https://map.naver.com")
```

3. 커밋 전 확인:

```bash
git status --ignored | grep naver_map_profile
```
