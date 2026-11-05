"""네이버 지도 '저장' 흐름을 흉내 낸 로컬 목업 서버 (QA 전용).
실제 네이버 지도 DOM 을 복제한 것이 아니라, 스크립트 로직(iframe 안 [저장] → 리스트 체크 → 메모 → 확인)을
검증하기 위한 가정 구조다. 저장 요청은 SAVED 리스트에 기록되고 /saved 로 조회된다."""
import json, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SAVED = []
NAV_CLICKS = []
LISTS = ["기본 리스트", "배민 매장", "맛집"]

MAIN = """<!doctype html><meta charset=utf-8><title>mock map</title>
<body style="margin:0">
<nav style="position:fixed;left:0;top:0;width:56px;height:100%%;display:flex;flex-direction:column;gap:8px;padding-top:60px">
  <button>지도 홈</button><button>길찾기</button><button>버스</button><button>기차</button>
  <button onclick="location.href='/p/favorite/myPlace'">저장</button><button>더보기</button>
</nav>
<iframe id=entryIframe src="/frame?q=%s" style="position:absolute;left:60px;top:0;width:400px;height:400px;border:0"></iframe>
<div style="position:absolute;left:480px;top:0">지도</div>
<div id=dlg role=dialog style="display:none;position:absolute;left:480px;top:40px;border:1px solid;background:#fff">
  <h2>저장</h2>%s
  <input id=memo placeholder="메모를 입력해 주세요">
  <button onclick="document.getElementById('dlg').style.display='none'">취소</button>
  <button id=ok>저장</button>
</div>
<script>
window.openSave = () => document.getElementById('dlg').style.display = 'block';
document.getElementById('ok').onclick = async () => {
  const lists = [...document.querySelectorAll('#dlg [role=checkbox]')]
      .filter(e => e.getAttribute('aria-checked') === 'true').map(e => e.getAttribute('aria-label'));
  await fetch('/save', {method:'POST', body: JSON.stringify({q: %s, lists, memo: document.getElementById('memo').value})});
  document.getElementById('dlg').style.display = 'none';
};
document.querySelectorAll('#dlg [role=checkbox]').forEach(e => e.onclick = () =>
  e.setAttribute('aria-checked', e.getAttribute('aria-checked') === 'true' ? 'false' : 'true'));
</script></body>"""

# 실제 화면 캡처(2026-11-05) 구조: 주소 제목 → 한 줄에 [☆][공유] ... [출발][도착]
FRAME = """<!doctype html><meta charset=utf-8><body>
<h2>%s</h2>
<div style="display:flex;align-items:center;gap:6px">
  %s
  <button aria-label="공유">⇪</button>
  <span style="flex:1"></span>
  <button>출발</button><button>도착</button>
</div>
<div>이 주소의 장소</div></body>"""
STAR_NAMED = '<button onclick="parent.openSave()"><span style="position:absolute;width:1px;height:1px;overflow:hidden">저장</span>☆</button>'
STAR_NONAME = '<button onclick="parent.openSave()">☆</button>'  # 이름 없는 아이콘 버튼


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, body, ctype="text/html; charset=utf-8"):
        b = body.encode()
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith("/p/search/"):
            q = urllib.parse.unquote(u.path[len("/p/search/"):])
            boxes = "".join(f'<div role=checkbox aria-checked=false aria-label="{n}">{n}</div>' for n in LISTS)
            self.send(MAIN % (urllib.parse.quote(q), boxes, json.dumps(q)))
        elif u.path == "/frame":
            q = urllib.parse.parse_qs(u.query).get("q", [""])[0]
            if "NOSAVE" in q:  # [저장] 버튼이 없는 화면 (실패/디버그 저장 경로 검증용)
                self.send(f"<!doctype html><meta charset=utf-8><body>검색결과 없음: {q}</body>")
            else:
                self.send(FRAME % (q, STAR_NONAME if "NONAME" in q else STAR_NAMED))
        elif u.path.startswith("/p/favorite"):
            NAV_CLICKS.append(u.path)  # 왼쪽 세로 메뉴 '저장'을 잘못 누른 경우
            self.send("<!doctype html><meta charset=utf-8><body><h2>저장 리스트</h2></body>")
        elif u.path == "/nav_clicks":
            self.send(json.dumps(NAV_CLICKS), "application/json")
        elif u.path == "/saved":
            self.send(json.dumps(SAVED, ensure_ascii=False), "application/json")
        else:
            self.send("<!doctype html><body>home</body>")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        SAVED.append(json.loads(self.rfile.read(n)))
        self.send("ok", "text/plain")


def serve(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    return srv
