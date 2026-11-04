"""naver_map_saver.py QA: 목업 서버 상대로 엑셀 → 저장 전 과정을 실행하고 결과를 검증한다.
실행: python tests/qa_naver_map_saver/run_qa.py"""
import json, os, shutil, subprocess, sys, tempfile, threading, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPT = ROOT / "scripts" / "naver_map_saver.py"
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "scripts"))
import mock_server
from naver_map_saver import split_address, build_memo

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  → {detail}"))
    fails += 0 if cond else 1

# 1) 주소 분리 단위 테스트
cases = [
    ("서울특별시 강남구 역삼동 123-4번지 2층 201호", "서울특별시 강남구 역삼동 123-4", "2층 201호"),
    ("서울특별시 마포구 서교동 395-12번지, 1층", "서울특별시 마포구 서교동 395-12", "1층"),
    ("경기도 수원시 팔달구 인계동 1000번지", "경기도 수원시 팔달구 인계동 1000", ""),
    ("서울특별시 용산구 한강대로23길 55", "서울특별시 용산구 한강대로23길 55", ""),
    ("  부산광역시 중구 남포동 1번지  지하1층 B101호 ", "부산광역시 중구 남포동 1", "지하1층 B101호"),
]
for addr, q, d in cases:
    check(f"split '{addr.strip()}'", split_address(addr) == (q, d), split_address(addr))
check("memo 순서 상호명 | 상세주소", build_memo("2층 201호", "맛있는국밥") == "맛있는국밥 | 2층 201호")
check("memo 상세주소 없음", build_memo("", "카페A") == "카페A")

# 2) 엑셀 생성
from openpyxl import Workbook
work = Path(tempfile.mkdtemp())
xlsx = work / "업체목록.xlsx"
wb = Workbook(); ws = wb.active
ws.append(["번호", "상호명", "주소"])
rows = [
    (1, "맛있는국밥", "서울특별시 강남구 역삼동 123-4번지 2층 201호"),
    (2, "카페A", "서울특별시 마포구 서교동 395-12번지, 1층"),
    (3, "도로명집", "서울특별시 용산구 한강대로23길 55"),
    (4, "주소없음", None),
    (5, "치킨B", "경기도 수원시 팔달구 인계동 1000번지 3층 302호"),
]
for r in rows: ws.append(r)
wb.save(xlsx)

# 3) 목업 서버 + 스크립트 실행 (리스트는 첫 행에서 2번 '배민 매장' 선택)
srv = mock_server.serve(); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}/p/search/"
cmd = [sys.executable, str(SCRIPT), str(xlsx), "--base-url", base, "--headless", "--auto-only",
       "--profile", str(work / "profile")]
if os.path.exists("/opt/pw-browsers/chromium"):
    cmd += ["--browser-path", "/opt/pw-browsers/chromium"]

def run(stdin):
    return subprocess.run(cmd, input=stdin, text=True, capture_output=True, cwd=work, timeout=300)

r1 = run("\n2\n")
print(r1.stdout[-1500:]); print(r1.stderr[-1500:])
saved = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/saved").read())
expected = [
    ("서울특별시 강남구 역삼동 123-4", "맛있는국밥 | 2층 201호"),
    ("서울특별시 마포구 서교동 395-12", "카페A | 1층"),
    ("서울특별시 용산구 한강대로23길 55", "도로명집"),
    ("경기도 수원시 팔달구 인계동 1000", "치킨B | 3층 302호"),
]
check("저장 건수 4 (빈 주소 행 제외)", len(saved) == 4, saved)
for (q, m), s in zip(expected, saved):
    check(f"검색어 '{q}'", s["q"] == q, s)
    check(f"  메모 '{m}'", s["memo"] == m, s)
    check("  리스트 = ['배민 매장'] 만 체크", s["lists"] == ["배민 매장"], s)
check("리스트 질문은 1번만", r1.stdout.count("저장할 리스트") == 1, r1.stdout.count("저장할 리스트"))
check("성공 기록 파일 생성", (work / "naver_map_saver_done.csv").exists())

# 4) 재실행 시 이미 저장한 행은 건너뜀 (중복 저장 방지)
r2 = run("\n")
saved2 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/saved").read())
check("재실행 시 중복 저장 없음", len(saved2) == 4, len(saved2))
check("재실행 시 건너뜀 4", "건너뜀 4" in r2.stdout, r2.stdout[-300:])

# 5) --list 지정 시 질문 없이 해당 리스트로 저장
(work / "naver_map_saver_done.csv").unlink()
r3 = subprocess.run(cmd + ["--list", "맛집", "--start", "5"], input="\n", text=True, capture_output=True, cwd=work, timeout=300)
saved3 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/saved").read())
check("--list 맛집: 질문 없음", "저장할 리스트" not in r3.stdout)
check("--list 맛집: 1건 저장, 리스트 맛집", len(saved3) == 5 and saved3[-1]["lists"] == ["맛집"], saved3[-1:])

# 6) [저장] 버튼이 없는 화면 → 실패 기록 + 디버그(캡처/버튼목록) 저장
xlsx2 = work / "실패케이스.xlsx"
wb2 = Workbook(); ws2 = wb2.active
ws2.append(["상호명", "주소"]); ws2.append(["없는집", "NOSAVE 테스트동 1번지 2층"])
wb2.save(xlsx2)
cmd2 = [c if c != str(xlsx) else str(xlsx2) for c in cmd]
r4 = subprocess.run(cmd2 + ["--list", "맛집"], input="\n", text=True, capture_output=True, cwd=work, timeout=300)
saved4 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/saved").read())
dbg = list((work / "naver_map_debug").glob("*_save_button.*")) if (work / "naver_map_debug").exists() else []
check("버튼 없음 → fail:save_button 출력", "fail:save_button" in r4.stdout, r4.stdout[-300:])
check("버튼 없음 → 저장 안 됨", len(saved4) == len(saved3))
check("버튼 없음 → 실패 기록 파일", (work / "naver_map_saver_failed.csv").exists())
check("디버그 캡처(.png)+버튼목록(.txt) 저장", {x.suffix for x in dbg} == {".png", ".txt"}, dbg)
if dbg:
    txt = [x for x in dbg if x.suffix == ".txt"][0].read_text(encoding="utf-8")
    check("버튼목록에 frame 정보 포함", "## frame" in txt, txt[:200])

srv.shutdown(); shutil.rmtree(work, ignore_errors=True)
print(f"\n=== QA 결과: 실패 {fails}건 ===")
sys.exit(1 if fails else 0)
