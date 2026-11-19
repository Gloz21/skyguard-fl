"""Builds the full dashboard state for a given moment of the demo."""
import json
import os
from datetime import timedelta

from anomaly import DeviationModel
from conflicts import check_flight, flight_times, iso, parse_iso
from notam import parse_notam
from sim import simulate_track

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _load(name):
    with open(os.path.join(DATA_DIR, name)) as f:
        return json.load(f)


class SkyGuard:
    def __init__(self):
        vdata = _load("vertiports.json")
        self.vertiports = {v["id"]: v for v in vdata["vertiports"]}
        self.launch_sites = vdata["launch_sites"]
        fdata = _load("flights.json")
        self.flights = fdata["flights"]
        self.demo_start = parse_iso(fdata["demo_start_utc"])
        ndata = _load("notams_live.json")
        self.notams_fetched = parse_iso(ndata["fetched_utc"])
        self.closures = [parse_notam(n["id"], n["text"]) for n in ndata["notams"]]
        self.model = DeviationModel().fit(
            [f for f in self.flights if not f.get("_scenario")], self.vertiports)
        self.tracks = {}
        for i, f in enumerate(self.flights):
            dep, _, _ = flight_times(f, self.vertiports)
            self.tracks[f["id"]] = simulate_track(f, self.vertiports, dep, seed=i + 1,
                                                  scenario=f.get("_scenario"))

    def state(self, minute, feed_outage=False):
        now = self.demo_start + timedelta(minutes=minute)
        feed_age = 45 if feed_outage else 5
        flights = []
        alerts = []
        for f in self.flights:
            plan = check_flight(f, self.vertiports, self.closures, feed_age)
            track = [p for p in self.tracks[f["id"]] if p["t"] <= now]
            full = self.tracks[f["id"]]
            # Flights with a CONFLICT or HOLD stay on the ground until a dispatcher decides.
            cleared = plan["status"] == "CLEAR"
            if not cleared:
                track = []
            airborne = bool(track) and now <= full[-1]["t"]
            a = (self.vertiports[f["from"]]["lat"], self.vertiports[f["from"]]["lon"])
            b = (self.vertiports[f["to"]]["lat"], self.vertiports[f["to"]]["lon"])
            sec = None
            if airborne:
                sec = self.model.score(track, a, b, f["cruise_ft"])
                if sec["risk"] != "LOW":
                    alerts.append({"flight_id": f["id"], **sec,
                                   "lat": track[-1]["lat"], "lon": track[-1]["lon"],
                                   "time_utc": iso(track[-1]["t"])})
            flights.append({**plan, "airborne": airborne, "landed": bool(track) and not airborne,
                            "position": ({"lat": track[-1]["lat"], "lon": track[-1]["lon"],
                                          "alt_ft": round(track[-1]["alt_ft"]),
                                          "gs_kt": round(track[-1]["gs_kt"])} if airborne else None),
                            "trail": [[p["lat"], p["lon"]] for p in track[-40:]] if airborne else [],
                            "security": sec})
        closures = []
        for c in self.closures:
            active = None
            if c.get("start_utc") or c.get("end_utc") or c.get("permanent"):
                s = parse_iso(c["start_utc"]) if c.get("start_utc") else None
                e = parse_iso(c["end_utc"]) if c.get("end_utc") else None
                active = (s is None or s <= now) and (e is None or now < e)
            closures.append({"id": c["id"], "active_now": active})
        return {"now_utc": iso(now), "minute": minute, "feed_outage": feed_outage,
                "data": {"notams_fetched_utc": iso(self.notams_fetched if not feed_outage else now - timedelta(minutes=45)),
                         "notam_age_min": feed_age,
                         "tracks_label": "SIMULATED flight tracks",
                         "notams_label": "SIMULATED FAA-style notices",
                         "model_training_points": self.model.n_training_points},
                "closures": closures, "flights": flights, "alerts": alerts}

    def static(self):
        keys = ("id", "category", "affects_aircraft", "polygon", "floor_ft", "ceiling_ft", "start_utc",
                "end_utc", "permanent", "needs_review", "problems", "parser_mode", "source_text",
                "center", "radius_nm", "raw_fields")
        routes = [{"flight_id": f["id"], "from": f["from"], "to": f["to"]} for f in self.flights]
        return {"vertiports": list(self.vertiports.values()), "launch_sites": self.launch_sites,
                "closures": [{k: c.get(k) for k in keys} for c in self.closures], "routes": routes,
                "demo_start_utc": iso(self.demo_start), "demo_minutes": 60}
