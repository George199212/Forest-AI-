"""
Fleet GPS Demo Adapter.

Generates deterministic synthetic vehicle GPS positions for sectors that
already exist in the database (no invented company/sector names) — most
positions land inside the sector's real boundary_json polygon; one
designated demo vehicle is placed just outside it so the sync
demonstrably exercises risk_rules.check_fleet_sector_exit() end to end.

Determinism: positions are seeded from the sector name + a 5-minute UTC
time bucket, so re-running sync() within the same bucket reproduces the
same coordinates (dedup key stays stable); a new bucket produces a new
"tick" of the simulated feed, like a real telematics stream would.

No network calls. No real vehicle/company identity implied — vehicle plate
numbers are synthetic (DEMO-xxx).
"""

import hashlib
from datetime import datetime, timezone

import database
from services.integrations import risk_rules
from services.integrations.categories import FleetIntegrationAdapter


def _seeded_offset(seed: str, spread: float = 0.002) -> tuple[float, float]:
    """Deterministic pseudo-random (dlat, dlon) in [-spread, spread] from a
    string seed — pure function, no RNG state, so repeated calls with the
    same seed always return the same offset."""
    digest = hashlib.sha256(seed.encode()).hexdigest()
    a = int(digest[:8], 16) / 0xFFFFFFFF  # [0, 1]
    b = int(digest[8:16], 16) / 0xFFFFFFFF
    return (a * 2 - 1) * spread, (b * 2 - 1) * spread


def _time_bucket() -> str:
    now = datetime.now(timezone.utc)
    bucket_minute = (now.minute // 5) * 5
    return now.strftime(f"%Y-%m-%dT%H:{bucket_minute:02d}:00Z")


class FleetGPSDemoAdapter(FleetIntegrationAdapter):
    provider = "fleet_gps_demo"
    display_name = "Fleet GPS (Demo)"
    is_demo_capable = True
    implemented = True

    DEMO_VEHICLES = ["DEMO-101", "DEMO-102"]

    def test_connection(self):
        return True, "Demo adapter — no external connection required."

    def authenticate(self):
        return True

    def fetch_data(self, **kwargs) -> list[dict]:
        bucket = _time_bucket()
        # database.py has no generic db() helper (that's api.py's) — query
        # directly, same pattern as services/geo.py::get_sector_row().
        import sqlite3
        conn = sqlite3.connect(database.DB_NAME)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT name, boundary_json FROM sectors "
                    "WHERE boundary_json IS NOT NULL AND boundary_json != '' LIMIT 3")
        sectors = [dict(r) for r in cur.fetchall()]
        conn.close()

        raw = []
        for i, sector in enumerate(sectors[:2]):
            import json
            try:
                boundary = json.loads(sector["boundary_json"])
            except (TypeError, ValueError):
                continue
            if not boundary:
                continue
            center_lat = sum(p[0] for p in boundary) / len(boundary)
            center_lon = sum(p[1] for p in boundary) / len(boundary)
            vehicle = self.DEMO_VEHICLES[i % len(self.DEMO_VEHICLES)]

            # One vehicle stays inside; the other is nudged well outside the
            # boundary (spread large enough to clear typical demo polygons)
            # so the sync visibly produces a FLEET_SECTOR_EXIT incident.
            if i == 0:
                dlat, dlon = _seeded_offset(f"{sector['name']}:{bucket}", spread=0.0015)
                inside = True
            else:
                dlat, dlon = _seeded_offset(f"{sector['name']}:{bucket}", spread=0.02)
                dlat += 0.02
                inside = False

            raw.append({
                "vehicle_plate": vehicle,
                "sector": sector["name"],
                "latitude": center_lat + dlat,
                "longitude": center_lon + dlon,
                "timestamp": bucket,
                "assumed_inside": inside,
            })
        return raw

    def normalize_data(self, raw_records: list[dict]) -> list[dict]:
        normalized = []
        for r in raw_records:
            normalized.append({
                "entity_type": "GPSPosition",
                "external_id": f"{r['vehicle_plate']}:{r['timestamp']}",
                "vehicle_id": r["vehicle_plate"],
                "gps_entity_type": "VEHICLE",
                "sector": r["sector"],
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "source_timestamp": r["timestamp"],
                "inside_boundary": 1 if r["assumed_inside"] else 0,
                "raw_payload": r,
            })
        return normalized

    def save_data(self, valid_records: list[dict]) -> dict:
        result = super().save_data(valid_records)
        for rec in valid_records:
            risk_rules.check_fleet_sector_exit(rec, is_demo=True)
        return result
