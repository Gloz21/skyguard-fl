"""Builds frontend/demo.html: the dashboard with every API answer baked in.

Use it as an offline backup for the demo (no server, no Wi-Fi needed):
  python backend/build_demo.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import server  # noqa: E402

root = os.path.join(os.path.dirname(__file__), "..", "frontend")
static = {**server.SKY.static(), "campus": {
    "base": server.CAMPUS.base, "landmarks": list(server.CAMPUS.landmarks.values()),
    "units": server.CAMPUS.units,
    "presets": [{"id": k, "text": v["text"]} for k, v in server.CAMPUS.demo.items()]}}
states = [[server.SKY.state(m, outage) for m in range(61)] for outage in (False, True)]
campus = [{k: server.CAMPUS.plan(v["text"], server.campus_now(stale), k) for k, v in server.CAMPUS.demo.items()}
          for stale in (False, True)]
snap = json.dumps({"static": static, "states": states, "campus": campus}, default=str, separators=(",", ":"))

with open(os.path.join(root, "index.html")) as f:
    html = f.read()
html = html.replace("<script>\nconst SNAP", f"<script>window.SKYGUARD_SNAPSHOT={snap};</script>\n<script>\nconst SNAP", 1)
with open(os.path.join(root, "demo.html"), "w") as f:
    f.write(html)
print(f"wrote frontend/demo.html ({len(html) // 1024} KB)")
