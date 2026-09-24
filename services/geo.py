"""
Shared geo helpers for demo scenarios (services/demo_scenarios.py) and any
other module that needs point/polygon math without importing bot.py (which
raises at import time if TELEGRAM_BOT_TOKEN is unset — not safe to import
from api.py). bot.py keeps its own local point_in_polygon/
calculate_distance_meters (untouched, still the ones the live geofence flow
uses) — these are separate copies of the same well-tested formulas, not a
refactor of that working code.
"""

import math
import sqlite3

import database


def point_in_polygon(lat, lon, polygon):
    """Ray casting algorithm. polygon: list of [lat, lon] pairs."""
    x, y = lon, lat
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][1], polygon[i][0]
        xj, yj = polygon[j][1], polygon[j][0]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_to_segment_m(lat, lon, lat1, lon1, lat2, lon2):
    """Approximate min distance from a point to a segment, in meters.
    Projects in a local equirectangular frame (fine at forestry-plot scale,
    a few km) rather than exact great-circle segment math."""
    lat0 = math.radians((lat1 + lat2) / 2.0)
    kx = 111320.0 * math.cos(lat0)
    ky = 110540.0

    px, py = lon * kx, lat * ky
    ax, ay = lon1 * kx, lat1 * ky
    bx, by = lon2 * kx, lat2 * ky

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def distance_to_polygon_edge_m(lat, lon, polygon):
    """Minimum distance in meters from (lat, lon) to the polygon's boundary
    (nearest edge), regardless of whether the point is inside or outside.
    polygon: list of [lat, lon] pairs."""
    n = len(polygon)
    if n < 2:
        return None
    best = None
    for i in range(n):
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[(i + 1) % n]
        d = _point_to_segment_m(lat, lon, lat1, lon1, lat2, lon2)
        if best is None or d < best:
            best = d
    return best


def get_sector_row(sector_name):
    """Return a sector row (dict) by exact name, or None."""
    conn = sqlite3.connect(database.DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM sectors WHERE name=?", (sector_name,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None
