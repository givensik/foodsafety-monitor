#!/usr/bin/env python3
"""
엑셀(또는 CSV)의 주소를 네이버 지도에서 검색해 '저장' 리스트(체크리스트)에 넣는 자동화 스크립트.

동작 순서 (행마다 반복)
  1. 주소에서 '번지' 앞부분만 잘라 네이버 지도에 검색
       예) "서울특별시 강남구 역삼동 123-4번지 2층 201호"
           → 검색어 : "서울특별시 강남구 역삼동 123-4"
           → 상세주소: "2층 201호"   ('번지' 단어 자체는 제외)
  2. 검색 결과의 [저장] 버튼 클릭
  3. 저장 창에서 리스트(체크리스트) 체크
       - 첫 행에서만 "어느 리스트에 넣을지" 번호로 물어봄
       - 이후 행은 같은 리스트에 자동으로 체크
  4. 메모 칸에 "상세주소 | 상호명" 입력 후 [저장]

사용법
  pip install playwright openpyxl
  python scripts/naver_map_saver.py 업체목록.xlsx
  python scripts/naver_map_saver.py 업체목록.xlsx --dry-run      # 브라우저 없이 분리 결과만 확인
  python scripts/naver_map_saver.py 업체목록.xlsx --addr-col 소재지 --name-col 업체명

로그인
  --profile 로 지정한 크롬 프로필(기본: naver_map_profile/)을 그대로 사용한다.
  처음 실행 시 로그인이 안 되어 있으면 열린 브라우저에서 직접 네이버 로그인 후 Enter.
  (프로필 폴더는 .gitignore 에 등록되어 있어 커밋되지 않는다 → docs/NAVER_MAP_PROFILE.md)

[주의 — 미검증] 아래 SELECTORS 의 버튼 문구/위치는 네이버 지도 화면을 직접 열어 확인하지 못한 상태로 작성했다.
자동 클릭이 실패하면 스크립트가 멈추고 "직접 처리 후 Enter" 를 요청하므로, 그때 실제 문구를 보고
SELECTORS 값을 고치면 된다.
"""
import argparse
import csv
import re
import sys
import time
import urllib.parse
from pathlib import Path

# ──────────────────────────────────────────────
# 화면 요소 문구 (미검증 — 실제 화면과 다르면 여기만 수정)
# ──────────────────────────────────────────────
SELECTORS = {
    "save_button_texts": ["저장"],                 # 검색 결과 패널의 저장 버튼
    "memo_placeholders": ["메모"],                 # 저장 창 메모 입력칸 placeholder 일부
    "confirm_button_texts": ["저장", "완료", "확인"],  # 저장 창 최종 확인 버튼
    "list_item_selector": "[role='checkbox'], input[type='checkbox'], label, li",
}

ADDR_COL_CANDIDATES = ["주소", "소재지", "SITE_ADDR", "도로명주소", "지번주소"]
NAME_COL_CANDIDATES = ["상호명", "업체명", "상호", "BSSH_NM"]
DONE_LOG = "naver_map_saver_done.csv"


# ──────────────────────────────────────────────
# 1. 주소 분리
# ──────────────────────────────────────────────
def split_address(addr: str):
    """'번지' 기준으로 (검색어, 상세주소) 반환. '번지'가 없으면 (전체주소, "")."""
    addr = (addr or "").strip()
    idx = addr.find("번지")
    if idx == -1:
        return addr, ""
    query = addr[:idx].strip()
    detail = addr[idx + len("번지"):].strip(" ,")
    return query, detail


def build_memo(detail: str, name: str) -> str:
    parts = [p for p in (detail.strip(), (name or "").strip()) if p]
    return " | ".join(parts)


# ──────────────────────────────────────────────
# 2. 엑셀/CSV 읽기
# ──────────────────────────────────────────────
def read_rows(path: Path):
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(path, read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(it)]
        return header, [["" if v is None else str(v) for v in r] for r in it]
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return [h.strip() for h in rows[0]], rows[1:]


def pick_col(header, wanted, candidates, label):
    if wanted:
        if wanted not in header:
            sys.exit(f"[오류] {label} 열 '{wanted}' 이 없습니다. 열 목록: {header}")
        return header.index(wanted)
    for c in candidates:
        if c in header:
            return header.index(c)
    sys.exit(f"[오류] {label} 열을 찾지 못했습니다. --{'addr' if label=='주소' else 'name'}-col 로 지정하세요. 열 목록: {header}")


def load_done(path: Path):
    if not path.exists():
        return set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {(r[0], r[1]) for r in csv.reader(f) if len(r) >= 2}


def mark_done(path: Path, addr, name, status):
    new = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["주소", "상호명", "결과", "시각"])
        w.writerow([addr, name, status, time.strftime("%Y-%m-%d %H:%M:%S")])


# ──────────────────────────────────────────────
# 3. 네이버 지도 조작
# ──────────────────────────────────────────────
def all_frames(page):
    return [page.main_frame] + [f for f in page.frames if f != page.main_frame]


def click_text_button(page, texts, timeout=5000):
    """모든 frame(searchIframe/entryIframe 포함)에서 문구가 일치하는 보이는 버튼을 클릭."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for fr in all_frames(page):
            for t in texts:
                loc = fr.get_by_role("button", name=re.compile(rf"^\s*{re.escape(t)}\s*$"))
                try:
                    for i in range(loc.count()):
                        el = loc.nth(i)
                        if el.is_visible():
                            el.click()
                            return True
                except Exception:
                    pass
        time.sleep(0.3)
    return False


def find_memo_input(page):
    for fr in all_frames(page):
        for ph in SELECTORS["memo_placeholders"]:
            loc = fr.locator(f"input[placeholder*='{ph}'], textarea[placeholder*='{ph}']")
            try:
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:
                pass
    return None


def visible_list_names(page):
    """저장 창 안의 리스트 이름 후보를 수집 (체크박스 옆 텍스트)."""
    names = []
    for fr in all_frames(page):
        for role in ("checkbox",):
            loc = fr.get_by_role(role)
            try:
                for i in range(loc.count()):
                    el = loc.nth(i)
                    if not el.is_visible():
                        continue
                    label = (el.get_attribute("aria-label") or el.inner_text() or "").strip()
                    if not label:
                        # input[type=checkbox] 인 경우 부모 label 텍스트
                        label = el.locator("xpath=ancestor::label[1]").inner_text().strip() if el.locator("xpath=ancestor::label[1]").count() else ""
                    if label:
                        names.append((label.splitlines()[0].strip(), el))
            except Exception:
                pass
    return names


def check_list(page, list_name):
    for label, el in visible_list_names(page):
        if label == list_name or label.startswith(list_name):
            checked = el.get_attribute("aria-checked") == "true" or (el.evaluate("e => e.checked === true"))
            if not checked:
                el.click()
            return True
    # 폴백: 텍스트로 직접 클릭
    for fr in all_frames(page):
        loc = fr.get_by_text(list_name, exact=True)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                return True
        except Exception:
            pass
    return False


def ask_list_name(page):
    items = visible_list_names(page)
    seen, uniq = set(), []
    for label, _ in items:
        if label not in seen:
            seen.add(label)
            uniq.append(label)
    print("\n=== 저장할 리스트(체크리스트)를 선택하세요 ===")
    for i, n in enumerate(uniq, 1):
        print(f"  {i}. {n}")
    ans = input("번호 입력 (목록에 없으면 리스트 이름을 직접 입력): ").strip()
    if ans.isdigit() and 1 <= int(ans) <= len(uniq):
        return uniq[int(ans) - 1]
    return ans


def manual(msg):
    input(f"  [수동 처리 필요] {msg} — 브라우저에서 직접 처리한 뒤 Enter (건너뛰려면 Enter 후 다음 행) ")


def save_one(page, query, memo, list_name, auto_only):
    page.goto("https://map.naver.com/p/search/" + urllib.parse.quote(query), wait_until="domcontentloaded")
    time.sleep(2.5)

    if not click_text_button(page, SELECTORS["save_button_texts"]):
        if auto_only:
            return "fail:save_button", list_name
        manual("[저장] 버튼을 찾지 못함. 검색 결과에서 직접 [저장] 클릭")
    time.sleep(1.2)

    if list_name is None:
        list_name = ask_list_name(page)
        print(f"  → 이후 모든 행을 '{list_name}' 리스트에 저장합니다.\n")

    if not check_list(page, list_name):
        if auto_only:
            return "fail:list", list_name
        manual(f"리스트 '{list_name}' 체크 실패. 직접 체크")

    memo_el = find_memo_input(page)
    if memo_el:
        memo_el.fill(memo)
    elif memo:
        if auto_only:
            return "fail:memo", list_name
        manual(f"메모 칸을 찾지 못함. 직접 입력: {memo}")

    # 저장 창 안의 확인 버튼 — 첫 [저장] 버튼과 문구가 같을 수 있어 마지막으로 보이는 버튼을 누른다
    clicked = False
    for fr in reversed(all_frames(page)):
        for t in SELECTORS["confirm_button_texts"]:
            loc = fr.get_by_role("button", name=re.compile(rf"^\s*{re.escape(t)}\s*$"))
            try:
                vis = [loc.nth(i) for i in range(loc.count()) if loc.nth(i).is_visible()]
                if vis:
                    vis[-1].click()
                    clicked = True
                    break
            except Exception:
                pass
        if clicked:
            break
    if not clicked:
        if auto_only:
            return "fail:confirm", list_name
        manual("최종 [저장] 버튼 클릭")
    time.sleep(1.0)
    return "ok", list_name


# ──────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="엑셀 주소 → 네이버 지도 저장 리스트 자동 등록")
    ap.add_argument("file", help=".xlsx 또는 .csv")
    ap.add_argument("--addr-col", help="주소 열 이름 (기본: 주소/소재지 자동 탐색)")
    ap.add_argument("--name-col", help="상호명 열 이름 (기본: 상호명/업체명 자동 탐색)")
    ap.add_argument("--profile", default="naver_map_profile", help="크롬 프로필 경로")
    ap.add_argument("--list", dest="list_name", help="저장 리스트 이름 (지정하면 처음에 묻지 않음)")
    ap.add_argument("--dry-run", action="store_true", help="브라우저 없이 검색어/메모 분리 결과만 출력")
    ap.add_argument("--auto-only", action="store_true", help="실패 시 수동 대기 없이 기록만 하고 다음 행으로")
    ap.add_argument("--start", type=int, default=1, help="시작 행 번호(1부터)")
    args = ap.parse_args()

    header, rows = read_rows(Path(args.file))
    ai = pick_col(header, args.addr_col, ADDR_COL_CANDIDATES, "주소")
    ni = pick_col(header, args.name_col, NAME_COL_CANDIDATES, "상호명")
    print(f"주소 열: '{header[ai]}', 상호명 열: '{header[ni]}', 총 {len(rows)}행")

    jobs = []
    for n, r in enumerate(rows, 1):
        if n < args.start or ai >= len(r) or not r[ai].strip():
            continue
        addr, name = r[ai].strip(), (r[ni].strip() if ni < len(r) else "")
        q, d = split_address(addr)
        jobs.append((n, addr, name, q, build_memo(d, name), "번지" in addr))

    if args.dry_run:
        for n, addr, name, q, memo, has in jobs:
            flag = "" if has else "  ※'번지' 없음 → 전체 주소로 검색"
            print(f"[{n}] 검색어='{q}'  메모='{memo}'{flag}")
        return

    from playwright.sync_api import sync_playwright
    done_path = Path(DONE_LOG)
    done = load_done(done_path)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(args.profile, headless=False, viewport={"width": 1400, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://map.naver.com/p/")
        input("네이버 로그인 상태를 확인하세요. 로그인 안 되어 있으면 브라우저에서 로그인 후 Enter: ")

        list_name = args.list_name
        ok = fail = skip = 0
        for n, addr, name, q, memo, has in jobs:
            if (addr, name) in done:
                skip += 1
                continue
            print(f"[{n}/{len(rows)}] {name} | 검색어='{q}' | 메모='{memo}'")
            try:
                status, list_name = save_one(page, q, memo, list_name, args.auto_only)
            except Exception as e:
                status = f"error:{type(e).__name__}"
            print(f"   → {status}")
            if status == "ok":
                ok += 1
                mark_done(done_path, addr, name, status)
            else:
                fail += 1
                mark_done(done_path.with_name("naver_map_saver_failed.csv"), addr, name, status)
        print(f"\n완료: 성공 {ok}, 실패 {fail}, 이미 처리되어 건너뜀 {skip}")
        print(f"성공 기록: {DONE_LOG} / 실패 기록: naver_map_saver_failed.csv")
        ctx.close()


if __name__ == "__main__":
    main()
