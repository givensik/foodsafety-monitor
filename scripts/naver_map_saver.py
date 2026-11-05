#!/usr/bin/env python3
"""
엑셀(또는 CSV)의 주소를 네이버 지도에서 검색해 '저장' 리스트(체크리스트)에 넣는 자동화 스크립트.

동작 순서 (행마다 반복)
  1. 주소에서 '번지' 앞부분만 잘라 네이버 지도에 검색
       예) "서울특별시 강남구 역삼동 123-4번지 2층 201호"
           → 검색어 : "서울특별시 강남구 역삼동 123-4"
           → 상세주소: "2층 201호"   ('번지' 단어 자체는 제외)
  2. 주소 제목 아래 ☆(저장) 버튼 클릭 (화면 맨 왼쪽 세로 메뉴의 '저장' 은 누르지 않음)
  3. 저장 창에서 '+메모, 별명, URL' 을 펼치고 메모 칸에 "상호명 | 상세주소" 입력
  4. 저장 리스트 클릭
       - 첫 행에서만 "어느 리스트에 넣을지" 번호로 물어봄
       - 이후 행은 같은 리스트에 자동으로 클릭
  5. 맨 아래 [저장] 클릭

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
    "save_button_texts": ["저장"],                 # 장소/주소 패널의 ☆ 저장 버튼 이름(aria-label·숨김 텍스트)
    # [확인된 팩트 — 2026-11-05 실제 화면 캡처] 주소 검색 시 왼쪽 패널에 주소 제목 아래
    #   ☆(저장) · 공유 아이콘 + [출발] [도착] 버튼이 한 줄로 나온다.
    #   화면 맨 왼쪽 세로 메뉴에도 '저장'(기차 아래)이 있는데, 이건 저장 리스트 화면으로 이동하는 메뉴라 누르면 안 된다.
    "anchor_texts": ["출발", "도착"],             # ☆ 버튼과 같은 줄에 있는 버튼 (위치 기준점)
    "share_texts": ["공유"],                      # ☆ 옆 공유 아이콘 (제외 대상)
    "nav_max_x": 90,                              # 이 x좌표(px)보다 왼쪽에 있는 요소 = 왼쪽 세로 메뉴로 보고 제외
    "nav_href_keywords": ["favorite", "bookmark", "/my"],  # 저장 리스트 화면으로 가는 링크 (제외 대상)
    "memo_placeholders": ["메모"],                 # 저장 창 메모 입력칸 placeholder 일부
    # [확인된 팩트 — 2026-11-05 승환 설명] ☆ 를 누르면 저장 창이 뜨고, 메모 칸은 '+메모, 별명, URL' 을 눌러야 펼쳐진다.
    #   그 아래 저장 리스트 중 하나를 클릭하고, 맨 아래 [저장] 을 누른다.
    "memo_toggle_texts": ["메모"],                # '+메모, 별명, URL' 펼치기 버튼 (이름에 '메모' 포함)
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
    parts = [p for p in ((name or "").strip(), detail.strip()) if p]
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


_CLICKABLE = "button, a, [role=button]"
_SCAN_JS = """(sel) => [...document.querySelectorAll(sel)].map((e, i) => {
    const r = e.getBoundingClientRect();
    const vis = r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
    const name = [e.getAttribute('aria-label'), e.getAttribute('title'), e.textContent]
        .filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
    return {i, vis, x: r.x, y: r.y, w: r.width, h: r.height, name, href: e.getAttribute('href') || ''};
})"""


def _frame_offset(fr):
    try:
        el = fr.frame_element()
        box = el.bounding_box()
        return (box["x"], box["y"]) if box else (0, 0)
    except Exception:
        return (0, 0)  # main frame


def _scan(fr):
    ox, oy = _frame_offset(fr)
    out = []
    for c in fr.evaluate(_SCAN_JS, _CLICKABLE):
        if not c["vis"]:
            continue
        c["x"] += ox; c["y"] += oy
        c["cx"] = c["x"] + c["w"] / 2; c["cy"] = c["y"] + c["h"] / 2
        c["frame"] = fr
        out.append(c)
    return out


def _is_nav(c):
    if c["x"] + c["w"] <= SELECTORS["nav_max_x"]:
        return True
    return any(k in c["href"] for k in SELECTORS["nav_href_keywords"])


def find_place_save_button(page):
    """주소/장소 패널의 ☆(저장) 버튼을 찾는다. 반환: (frame, index) 또는 None.
    1순위: 이름에 '저장'이 들어간 버튼 중 [출발]/[도착] 버튼과 가장 가까운 것 (왼쪽 세로 메뉴 제외)
    2순위: 이름이 없더라도 [출발] 버튼과 같은 줄·왼쪽에 있는 아이콘 버튼 중 가장 왼쪽 것 (공유 제외)"""
    cands = []
    for fr in all_frames(page):
        try:
            cands += _scan(fr)
        except Exception:
            pass
    cands = [c for c in cands if not _is_nav(c)]
    anchors = [c for c in cands
               if any(re.fullmatch(rf"\s*{re.escape(t)}\s*", c["name"]) for t in SELECTORS["anchor_texts"])]
    named = [c for c in cands
             if any(t in c["name"] for t in SELECTORS["save_button_texts"])
             and not any(a is c for a in anchors)]

    if anchors:
        a = min(anchors, key=lambda c: c["x"])  # [출발]
        if named:
            best = min(named, key=lambda c: (c["frame"] is not a["frame"], abs(c["cy"] - a["cy"]) + abs(c["cx"] - a["cx"])))
            if abs(best["cy"] - a["cy"]) < 60:
                return best["frame"], best["i"]
        row = [c for c in cands
               if c["frame"] is a["frame"] and abs(c["cy"] - a["cy"]) < 25 and c["cx"] < a["x"]
               and not any(t in c["name"] for t in SELECTORS["share_texts"])]
        if row:
            best = min(row, key=lambda c: c["x"])
            return best["frame"], best["i"]
    if named:
        best = min(named, key=lambda c: c["y"])
        return best["frame"], best["i"]
    return None


def click_place_save_button(page, timeout=8000):
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        hit = find_place_save_button(page)
        if hit:
            fr, i = hit
            fr.locator(_CLICKABLE).nth(i).click()
            return True
        time.sleep(0.5)
    return False


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


_INPUTS_JS = """() => [...document.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea')]
    .map((e, i) => { const r = e.getBoundingClientRect(); return {i, vis: r.width > 0 && r.height > 0}; })
    .filter(o => o.vis).map(o => o.i)"""
_INPUT_SEL = "input:not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea"


def _visible_inputs(page):
    out = set()
    for fr in all_frames(page):
        try:
            out |= {(fr, i) for i in fr.evaluate(_INPUTS_JS)}
        except Exception:
            pass
    return out


def find_memo_input(page, before=None):
    """1순위: placeholder 에 '메모' 가 들어간 입력칸.
    2순위: '+메모, 별명, URL' 을 펼친 뒤 새로 나타난 입력칸 중 첫 번째 (메모·별명·URL 순서이므로)."""
    for fr in all_frames(page):
        for ph in SELECTORS["memo_placeholders"]:
            loc = fr.locator(f"input[placeholder*='{ph}'], textarea[placeholder*='{ph}']")
            try:
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:
                pass
    if before is not None:
        new = sorted(_visible_inputs(page) - before, key=lambda x: x[1])
        if new:
            fr, i = new[0]
            return fr.locator(_INPUT_SEL).nth(i)
    return None


def open_memo_section(page, timeout=4000):
    """'+메모, 별명, URL' 펼치기 버튼 클릭. 이미 메모 칸이 보이면 누르지 않는다."""
    if find_memo_input(page):
        return True
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        cands = []
        for fr in all_frames(page):
            try:
                cands += _scan(fr)
            except Exception:
                pass
        cands = [c for c in cands if not _is_nav(c)
                 and any(t in c["name"] for t in SELECTORS["memo_toggle_texts"])]
        if cands:
            c = min(cands, key=lambda c: len(c["name"]))
            c["frame"].locator(_CLICKABLE).nth(c["i"]).click()
            return True
        time.sleep(0.4)
    return False


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
                        names.append((label.splitlines()[0].strip(), el, fr))
            except Exception:
                pass
    return names


def check_list(page, list_name):
    for label, el, fr in visible_list_names(page):
        if label == list_name or label.startswith(list_name):
            checked = el.get_attribute("aria-checked") == "true" or (el.evaluate("e => e.checked === true"))
            if not checked:
                el.click()
            return fr
    # 폴백: 텍스트로 직접 클릭
    for fr in all_frames(page):
        loc = fr.get_by_text(list_name, exact=True)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                return fr
        except Exception:
            pass
    return None


def ask_list_name(page):
    items = visible_list_names(page)
    seen, uniq = set(), []
    for label, _, _ in items:
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


DEBUG_DIR = Path("naver_map_debug")


def dump_debug(page, step):
    """막힌 순간의 화면 캡처 + frame 별 보이는 버튼/입력칸 목록을 naver_map_debug/ 에 저장.
    이 폴더를 그대로 전달하면 SELECTORS 를 실제 화면에 맞게 고칠 수 있다."""
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        stamp = time.strftime("%H%M%S")
        page.screenshot(path=str(DEBUG_DIR / f"{stamp}_{step}.png"), full_page=True)
        lines = [f"URL: {page.url}", f"단계: {step}", ""]
        for fr in all_frames(page):
            lines.append(f"## frame name='{fr.name}' url={fr.url}")
            try:
                info = fr.evaluate("""() => [...document.querySelectorAll(
                    'button, a[role=button], [role=button], [role=checkbox], input, textarea')]
                  .filter(e => e.offsetParent !== null)
                  .slice(0, 150)
                  .map(e => [e.tagName, e.getAttribute('role') || '', (e.innerText || '').trim().slice(0, 30),
                             e.getAttribute('aria-label') || '', e.getAttribute('placeholder') || '',
                             e.className && e.className.toString ? e.className.toString().slice(0, 40) : ''].join(' | '))""")
                lines += ["  " + x for x in info]
            except Exception as e:
                lines.append(f"  (읽기 실패: {e})")
        (DEBUG_DIR / f"{stamp}_{step}.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"  [디버그] {DEBUG_DIR}/{stamp}_{step}.png / .txt 저장")
    except Exception as e:
        print(f"  [디버그 저장 실패] {e}")


def manual(msg, page=None, step="manual"):
    if page is not None:
        dump_debug(page, step)
    input(f"  [수동 처리 필요] {msg} — 브라우저에서 직접 처리한 뒤 Enter (건너뛰려면 Enter 후 다음 행) ")


def click_confirm(page, dialog_frame=None):
    """저장 창 맨 아래 [저장] 버튼 클릭.
    ☆ 버튼·왼쪽 세로 메뉴도 이름이 '저장' 일 수 있으므로, 이름이 정확히 확인 문구인 버튼 중
    왼쪽 메뉴를 빼고 화면에서 가장 아래(y 최대)에 있는 것을 누른다."""
    cands = []
    for fr in all_frames(page):
        try:
            cands += _scan(fr)
        except Exception:
            pass
    for t in SELECTORS["confirm_button_texts"]:
        hit = [c for c in cands if not _is_nav(c) and re.fullmatch(rf"\s*{re.escape(t)}\s*", c["name"])]
        if hit:
            c = max(hit, key=lambda c: c["cy"])
            c["frame"].locator(_CLICKABLE).nth(c["i"]).click()
            return True
    return False


def save_one(page, base_url, query, memo, list_name, auto_only):
    page.goto(base_url + urllib.parse.quote(query), wait_until="domcontentloaded")
    time.sleep(2.5)

    if not click_place_save_button(page):
        if auto_only:
            dump_debug(page, "save_button")
            return "fail:save_button", list_name
        manual("☆(저장) 버튼을 찾지 못함. 주소 제목 아래 [출발] 왼쪽의 ☆ 를 직접 클릭", page, "save_button")
    time.sleep(1.2)

    # ③ '+메모, 별명, URL' 펼치기 → ④ 메모 입력
    if memo:
        before = _visible_inputs(page)
        open_memo_section(page)
        time.sleep(0.6)
        memo_el = find_memo_input(page, before)
        if memo_el:
            memo_el.fill(memo)
        else:
            if auto_only:
                dump_debug(page, "memo")
                return "fail:memo", list_name
            manual(f"'+메모, 별명, URL' 을 눌러 메모 칸에 직접 입력: {memo}", page, "memo")

    # ⑤ 저장 리스트 클릭 (첫 행에서만 어느 리스트인지 물어봄)
    if list_name is None:
        list_name = ask_list_name(page)
        print(f"  → 이후 모든 행을 '{list_name}' 리스트에 저장합니다.\n")

    dialog_frame = check_list(page, list_name)
    if dialog_frame is None:
        if auto_only:
            dump_debug(page, "list")
            return "fail:list", list_name
        manual(f"리스트 '{list_name}' 체크 실패. 직접 클릭", page, "list")

    # ⑥ 맨 아래 [저장]
    if not click_confirm(page, dialog_frame):
        if auto_only:
            dump_debug(page, "confirm")
            return "fail:confirm", list_name
        manual("최종 [저장] 버튼 클릭", page, "confirm")
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
    ap.add_argument("--base-url", default="https://map.naver.com/p/search/", help=argparse.SUPPRESS)  # QA용
    ap.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)  # QA용
    ap.add_argument("--browser-path", help="크롬 실행 파일 경로 (playwright install 대신 설치된 크롬 사용 시)")
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
        opts = {"headless": args.headless, "viewport": {"width": 1400, "height": 900}}
        if args.browser_path:
            opts["executable_path"] = args.browser_path
        ctx = p.chromium.launch_persistent_context(args.profile, **opts)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(args.base_url.rsplit("/search/", 1)[0] + "/")
        input("네이버 로그인 상태를 확인하세요. 로그인 안 되어 있으면 브라우저에서 로그인 후 Enter: ")

        list_name = args.list_name
        ok = fail = skip = 0
        for n, addr, name, q, memo, has in jobs:
            if (addr, name) in done:
                skip += 1
                continue
            print(f"[{n}/{len(rows)}] {name} | 검색어='{q}' | 메모='{memo}'")
            try:
                status, list_name = save_one(page, args.base_url, q, memo, list_name, args.auto_only)
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
