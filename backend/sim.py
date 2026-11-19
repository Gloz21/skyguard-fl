"""SIMULATED flight tracks (labeled as simulated in the UI).

In a real system these would come from ADS-B / Remote ID position reports.
"""
import math
import random
from datetime import timedelta

from geo import PROJ, haversine_nm

STEP_S = 30          # one position report every 30 seconds
CLIMB_NM = 2.0       # climb / descend over the first and last 2 nm


def planned_alt(along_nm, total_nm, cruise_ft):
    edge = min(along_nm, total_nm - along_nm)
    return cruise_ft * max(0.0, min(1.0, edge / CLIMB_NM))


def _route_frame(a, b):
    ax, ay = PROJ.to_xy(*a)
    bx, by = PROJ.to_xy(*b)
    length = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / length, (by - ay) / length
    return (ax, ay), (ux, uy), (-uy, ux), length  # origin, along unit, left unit, length


def simulate_track(flight, vp, dep, seed=0, scenario=None):
    rng = random.Random(seed)
    a = (vp[flight["from"]]["lat"], vp[flight["from"]]["lon"])
    b = (vp[flight["to"]]["lat"], vp[flight["to"]]["lon"])
    (ox, oy), (ux, uy), (lx, ly), length = _route_frame(a, b)
    cruise, speed = flight["cruise_ft"], flight["speed_kt"]

    pts, along, lateral, t = [], 0.0, 0.0, 0
    loiter_center = None
    while True:
        minute = t / 60
        gs = speed + rng.gauss(0, 4)
        alt_target = planned_alt(along, length, cruise)
        lateral = 0.85 * lateral + rng.gauss(0, 0.04)  # small natural wander
        x = ox + ux * along + lx * lateral
        y = oy + uy * along + ly * lateral

        if scenario == "security_deviation" and minute >= 12:
            # Drifts off route, descends, then circles over a rural area.
            k = min(minute - 12, 6)
            drift = 0.55 * k
            x = ox + ux * along + lx * (lateral - drift)
            y = oy + uy * along + ly * (lateral - drift)
            alt_target = cruise - (cruise - 300) * k / 6
            gs = speed - (speed - 45) * k / 6 + rng.gauss(0, 3)
            if minute >= 18:
                if loiter_center is None:
                    loiter_center = (x, y)
                ang = (minute - 18) * 2 * math.pi / 2.5
                x = loiter_center[0] + 0.3 * math.cos(ang)
                y = loiter_center[1] + 0.3 * math.sin(ang)
                alt_target = 300
                gs = 45 + rng.gauss(0, 3)
            if minute > 32:
                break

        lat, lon = PROJ.to_latlon(x, y)
        pts.append({"t": dep + timedelta(seconds=t), "lat": lat, "lon": lon,
                    "alt_ft": max(0, alt_target + rng.gauss(0, 40)), "gs_kt": max(0, gs)})
        if scenario != "security_deviation" or minute < 12:
            along += max(gs, 0) * STEP_S / 3600
        if along >= length and scenario is None:
            break
        if along >= length:
            along = length
        t += STEP_S
    return pts
