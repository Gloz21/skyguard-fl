"""Geometry helpers. All distance math happens here, in code, never in the LLM.

Uses a local flat-earth projection (fine for distances under ~150 nm).
Units: nautical miles (nm), degrees, feet.
"""
import math

NM_PER_DEG_LAT = 60.0


def haversine_nm(lat1, lon1, lat2, lon2):
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_nm * math.asin(math.sqrt(a))


class LocalProjection:
    """Projects lat/lon to x/y in nm around a reference latitude."""

    def __init__(self, ref_lat=28.3):
        self.k = math.cos(math.radians(ref_lat)) * NM_PER_DEG_LAT

    def to_xy(self, lat, lon):
        return lon * self.k, lat * NM_PER_DEG_LAT

    def to_latlon(self, x, y):
        return y / NM_PER_DEG_LAT, x / self.k


PROJ = LocalProjection()


def interpolate(a, b, f):
    """Point a fraction f of the way from a=(lat,lon) to b."""
    return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f


def offset_point(lat, lon, dx_nm, dy_nm):
    x, y = PROJ.to_xy(lat, lon)
    return PROJ.to_latlon(x + dx_nm, y + dy_nm)


def cross_track_nm(p, a, b):
    """Shortest distance (nm) from point p to segment a-b, plus fraction along it."""
    px, py = PROJ.to_xy(*p)
    ax, ay = PROJ.to_xy(*a)
    bx, by = PROJ.to_xy(*b)
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), t


def point_in_polygon(p, poly):
    """Ray casting. p=(lat,lon), poly=[(lat,lon), ...]."""
    x, y = PROJ.to_xy(*p)
    pts = [PROJ.to_xy(*q) for q in poly]
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def circle_polygon(center, radius_nm, n=48):
    lat, lon = center
    return [offset_point(lat, lon, radius_nm * math.cos(2 * math.pi * i / n),
                         radius_nm * math.sin(2 * math.pi * i / n)) for i in range(n)]


def segment_hits_area(a, b, area_poly, step_nm=0.25):
    """Samples the route a->b and returns fractions (0..1) where it is inside the area."""
    length = haversine_nm(*a, *b)
    n = max(2, int(length / step_nm))
    hits = []
    for i in range(n + 1):
        f = i / n
        if point_in_polygon(interpolate(a, b, f), area_poly):
            hits.append(f)
    return hits
