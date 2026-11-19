"""SkyGuard FL web server. Standard library only, so it runs anywhere (including Cloud Run).

  python backend/server.py            -> http://localhost:8080
"""
import json
import os
import sys
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))
from campus import CampusDispatch  # noqa: E402
from conflicts import iso  # noqa: E402
from notam import gemini_available  # noqa: E402
from state import SkyGuard  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "frontend")
CAMPUS_NOW_MIN = 15          # campus mode uses demo time 17:45Z
STALE_WEATHER_NOW_MIN = 90   # "simulate stale weather" jumps campus time forward

SKY = SkyGuard()
CAMPUS = CampusDispatch(SKY.closures)
DECISIONS = []  # in-memory decision log (use Firestore in production)


def campus_now(stale):
    return iso(SKY.demo_start + timedelta(minutes=STALE_WEATHER_NOW_MIN if stale else CAMPUS_NOW_MIN))


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/api/static":
            return self._json({**SKY.static(), "campus": {"base": CAMPUS.base,
                               "landmarks": list(CAMPUS.landmarks.values()), "units": CAMPUS.units,
                               "presets": [{"id": k, "text": v["text"]} for k, v in CAMPUS.demo.items()]},
                               "live_ai": gemini_available()})
        if url.path == "/api/state":
            minute = max(0, min(60, int(q.get("minute", ["0"])[0])))
            return self._json(SKY.state(minute, q.get("outage", ["0"])[0] == "1"))
        if url.path == "/api/decisions":
            return self._json(DECISIONS)
        path = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
        full = os.path.realpath(os.path.join(ROOT, path))
        if not full.startswith(os.path.realpath(ROOT)) or not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if full.endswith(".html") else "application/octet-stream")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            body = self._body()
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        if self.path == "/api/campus/plan":
            text = str(body.get("text", ""))[:1000].strip()
            if not text:
                return self._json({"error": "empty report"}, 400)
            return self._json(CAMPUS.plan(text, campus_now(bool(body.get("stale_weather"))),
                                          body.get("incident_id")))
        if self.path == "/api/decision":
            entry = {k: str(body.get(k, ""))[:300] for k in ("who", "item", "action", "note")}
            DECISIONS.append(entry)
            return self._json({"ok": True, "count": len(DECISIONS)})
        return self._json({"error": "not found"}, 404)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"SkyGuard FL on http://localhost:{port}  (live AI: {gemini_available()})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
