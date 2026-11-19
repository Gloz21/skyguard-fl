"""Route-deviation anomaly detection.

The model learns what NORMAL flights look like (how far they wander off the line,
how much altitude varies, how fast they go), then scores live tracks against that
baseline. It flags; a human decides what to do.
"""
import statistics
from datetime import datetime, timezone

from geo import cross_track_nm, haversine_nm
from sim import planned_alt, simulate_track

WINDOW = 4          # last 4 reports = 2 minutes
Z_FLAG = 4.0        # flag when a feature is 4+ standard deviations from normal
EDGE_NM = 2.5       # ignore altitude/speed checks near vertiports (takeoff/landing)


def features(pt, a, b, cruise_ft):
    xt, frac = cross_track_nm((pt["lat"], pt["lon"]), a, b)
    total = haversine_nm(*a, *b)
    along = frac * total
    near_edge = min(along, total - along) < EDGE_NM
    return {"xtrack_nm": xt, "alt_dev_ft": pt["alt_ft"] - planned_alt(along, total, cruise_ft),
            "gs_kt": pt["gs_kt"], "near_edge": near_edge}


class DeviationModel:
    def __init__(self):
        self.stats = {}

    def fit(self, flights, vp, n_per_route=12):
        rows = []
        for f in flights:
            a = (vp[f["from"]]["lat"], vp[f["from"]]["lon"])
            b = (vp[f["to"]]["lat"], vp[f["to"]]["lon"])
            for s in range(n_per_route):
                dep = datetime(2026, 1, 1, tzinfo=timezone.utc)
                for p in simulate_track(f, vp, dep, seed=1000 + s * 7 + sum(map(ord, f["id"])) % 97):
                    rows.append(features(p, a, b, f["cruise_ft"]))
        cruise_rows = [r for r in rows if not r["near_edge"]]
        for key, src in (("xtrack_nm", rows), ("alt_dev_ft", cruise_rows), ("gs_kt", cruise_rows)):
            vals = [r[key] for r in src]
            self.stats[key] = (statistics.mean(vals), statistics.pstdev(vals) or 1e-6)
        self.n_training_points = len(rows)
        return self

    def score(self, track, a, b, cruise_ft):
        """Scores the latest WINDOW points. Returns flags, z-scores and a risk level."""
        recent = [features(p, a, b, cruise_ft) for p in track[-WINDOW:]]
        if len(recent) < WINDOW:
            return {"risk": "LOW", "flags": [], "z": {}, "off_route_nm": round(recent[-1]["xtrack_nm"], 2) if recent else 0}
        mx, sx = self.stats["xtrack_nm"]
        ma, sa = self.stats["alt_dev_ft"]
        mg, sg = self.stats["gs_kt"]
        avg = lambda k: sum(r[k] for r in recent) / len(recent)
        cruise_phase = not any(r["near_edge"] for r in recent)
        z = {"drift": (avg("xtrack_nm") - mx) / sx,
             "descent": (ma - avg("alt_dev_ft")) / sa if cruise_phase else 0.0,
             "slow": (mg - avg("gs_kt")) / sg if cruise_phase else 0.0}
        flags = []
        if z["drift"] > Z_FLAG:
            flags.append("DRIFT")
        if z["descent"] > Z_FLAG:
            flags.append("UNEXPECTED_DESCENT")
        if z["slow"] > Z_FLAG:
            flags.append("LOITER")
        off = recent[-1]["xtrack_nm"]
        risk = "HIGH" if len(flags) >= 2 or off > 2 else ("MEDIUM" if flags else "LOW")
        return {"risk": risk, "flags": flags, "z": {k: round(v, 1) for k, v in z.items()},
                "off_route_nm": round(off, 2), "alt_ft": round(track[-1]["alt_ft"]),
                "gs_kt": round(track[-1]["gs_kt"])}
