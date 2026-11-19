"""Flight vs. closure checks. Pure code: times, distances, altitudes, suggestions."""
from datetime import datetime, timedelta

from geo import cross_track_nm, haversine_nm, interpolate, point_in_polygon, segment_hits_area

STALE_AFTER_MIN = 30      # NOTAM data older than this -> HOLD everything
BUFFER_MIN = 15           # wait this long after a closure ends before departing
ALT_MAX_NM = 40.0        # alternates must be within this distance of the blocked vertiport
NEAR_NM = 2.0             # warn when a route passes this close to a closure


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def flight_times(flight, vp):
    a, b = vp[flight["from"]], vp[flight["to"]]
    dist = haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
    dep = parse_iso(flight["depart_utc"])
    arr = dep + timedelta(hours=dist / flight["speed_kt"])
    return dep, arr, dist


def _time_overlap(dep, arr, c):
    start = parse_iso(c["start_utc"]) if c.get("start_utc") else None
    end = parse_iso(c["end_utc"]) if c.get("end_utc") else None
    if start and arr <= start:
        return False
    if end and dep >= end:
        return False
    return True


def _alt_overlap(cruise_ft, c):
    lo = c.get("floor_ft") or 0
    hi = c.get("ceiling_ft") if c.get("ceiling_ft") is not None else 99999
    return lo <= cruise_ft <= hi or lo == 0  # every flight passes through low altitude near vertiports


def min_gap_nm(a, b, poly):
    """Approximate closest approach of route a-b to the closure edge."""
    best = float("inf")
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        for f in [k / 20 for k in range(21)]:
            d, _ = cross_track_nm(interpolate(p, q, f), a, b)
            best = min(best, d)
    return best


def route_check(a, b, dep, arr, cruise_ft, closures):
    hits, near = [], []
    for c in closures:
        if not c.get("affects_aircraft") or not c.get("polygon"):
            continue
        if not _time_overlap(dep, arr, c) or not _alt_overlap(cruise_ft, c):
            continue
        if segment_hits_area(a, b, c["polygon"]):
            hits.append(c["id"])
        else:
            gap = min_gap_nm(a, b, c["polygon"])
            if gap < NEAR_NM:
                near.append({"id": c["id"], "gap_nm": round(gap, 2)})
    return hits, near


def check_flight(flight, vp, closures, feed_age_min):
    dep, arr, dist = flight_times(flight, vp)
    a = (vp[flight["from"]]["lat"], vp[flight["from"]]["lon"])
    b = (vp[flight["to"]]["lat"], vp[flight["to"]]["lon"])
    result = {"flight_id": flight["id"], "from": flight["from"], "to": flight["to"],
              "depart_utc": iso(dep), "arrive_utc": iso(arr), "distance_nm": round(dist, 1),
              "status": "CLEAR", "reasons": [], "conflicts": [], "near": [], "suggestions": []}

    # Safe defaults first.
    if feed_age_min > STALE_AFTER_MIN:
        result["status"] = "HOLD"
        result["reasons"].append(f"NOTAM data is {feed_age_min} min old (limit {STALE_AFTER_MIN}). Refresh before flying.")
        return result
    unreadable = [c["id"] for c in closures if c.get("needs_review") and c.get("affects_aircraft", True)]
    if unreadable:
        result["status"] = "HOLD"
        result["reasons"].append("A notice could not be verified: " + ", ".join(unreadable) + ". Human review needed.")
        return result

    hits, near = route_check(a, b, dep, arr, flight["cruise_ft"], closures)
    result["near"] = near
    if not hits:
        if near:
            result["reasons"].append("Clear, but passes within " + ", ".join(f"{n['gap_nm']} nm of {n['id']}" for n in near))
        return result

    result["status"] = "CONFLICT"
    result["conflicts"] = hits
    result["reasons"].append("Route crosses active closure " + ", ".join(hits) + " during the flight.")

    # Suggestion 1: delay until the latest blocking closure ends (+ buffer), verified in code.
    ends = [parse_iso(c["end_utc"]) for c in closures if c["id"] in hits and c.get("end_utc")]
    if ends and len(ends) == len(hits):
        new_dep = max(ends) + timedelta(minutes=BUFFER_MIN)
        new_arr = new_dep + (arr - dep)
        h2, _ = route_check(a, b, new_dep, new_arr, flight["cruise_ft"], closures)
        if not h2:
            delay = int((new_dep - dep).total_seconds() // 60)
            result["suggestions"].append({"type": "DELAY", "new_depart_utc": iso(new_dep),
                                          "delay_min": delay,
                                          "text": f"Depart {iso(new_dep)[11:16]}Z ({delay} min later), after the closure ends + {BUFFER_MIN} min buffer."})

    # Suggestion 2: swap the Space Coast end of the trip to another vertiport with a clear route.
    hit_polys = [c["polygon"] for c in closures if c["id"] in hits]
    for alt_id, alt in vp.items():
        if alt_id in (flight["from"], flight["to"]):
            continue
        for end_label, na, nb in (("to", a, (alt["lat"], alt["lon"])), ("from", (alt["lat"], alt["lon"]), b)):
            end_pt = b if end_label == "to" else a
            # only swap the end of the trip that sits inside the closure
            if not any(point_in_polygon(end_pt, poly) for poly in hit_polys):
                continue
            if haversine_nm(*end_pt, alt["lat"], alt["lon"]) > ALT_MAX_NM:
                continue  # an "alternate" 70 nm away is not a real alternate
            d2 = haversine_nm(*na, *nb)
            arr2 = dep + timedelta(hours=d2 / flight["speed_kt"])
            h3, _ = route_check(na, nb, dep, arr2, flight["cruise_ft"], closures)
            if not h3 and d2 > 5:
                result["suggestions"].append({"type": "ALTERNATE", "swap": end_label, "vertiport": alt_id,
                                              "distance_nm": round(d2, 1),
                                              "text": f"Use {alt['name']} as the {'destination' if end_label == 'to' else 'departure'} instead (on time, {d2:.0f} nm)."})
    return result
