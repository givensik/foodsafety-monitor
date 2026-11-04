"""네이버 지도 '저장' 흐름을 흉내 낸 로컬 목업 서버 (QA 전용).
실제 네이버 지도 DOM 을 복제한 것이 아니라, 스크립트 로직(iframe 안 [저장] → 리스트 체크 → 메모 → 확인)을
검증하기 위한 가정 구조다. 저장 요청은 SAVED 리스트에 기록되고 /saved 로 조회된다."""
import json, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SAVED = []
LISTS = ["기본 리스트", "배민 매장", "맛집"]

MAIN = """<!doctype html><meta charset=utf-8><title>mock map</title>
<body><h1>지도</h1><iframe id=searchIframe src="/frame?q=%s" style="width:400px;height:300px"></iframe>
<div id=dlg role=dialog style="display:none;border:1px solid">
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

FRAME = """<!doctype html><meta charset=utf-8><body><div>검색결과: %s</div>
<button onclick="parent.openSave()">저장</button><button>공유</button></body>"""


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
            self.send(FRAME % urllib.parse.parse_qs(u.query).get("q", [""])[0])
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
