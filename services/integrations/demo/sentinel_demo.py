"""
Sentinel Demo Adapter.

Wraps the tier/scoring vocabulary already defined in
services/satellite_intelligence/ (TIER_1_BASELINE etc.) rather than
inventing a second one — this adapter's job is only to fabricate a
deterministic "scene" per sync (no Copernicus network call) and route it
through the same satellite_observations table
services/satellite_intelligence/providers/sentinel.py's LIVE path already
writes to (via categories.SatelliteIntegrationAdapter.save_data). It does
NOT call the real decision engine (decide_tier/decide_and_request) — that
stays reserved for actual Sentinel Hub responses; this only demonstrates
the sync -> normalize -> save -> risk-event pipeline end to end.

Determinism: one sector (deterministically chosen by name) is flagged
change_detected=True per UTC day, so the sync is repeatable within a day
and demonstrably produces a SATELLITE_UNREGISTERED_CHANGE risk event if
that sector has no recent registered timber movements.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone

import database
from services.integrations import risk_rules
from services.integrations.categories import SatelliteIntegrationAdapter
from services.satellite_intelligence.models import TIER_1_BASELINE


class SentinelDemoAdapter(SatelliteIntegrationAdapter):
    provider = "sentinel_demo"
    display_name = "Sentinel (Demo)"
    is_demo_capable = True
    implemented = True

    def test_connection(self):
        return True, "Demo adapter — no external connection required."

    def authenticate(self):
        return True

    def fetch_data(self, **kwargs) -> list[dict]:
        conn = sqlite3.connect(database.DB_NAME)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT name FROM sectors WHERE boundary_json IS NOT NULL "
                    "AND boundary_json != '' ORDER BY name LIMIT 5")
        sectors = [r["name"] for r in cur.fetchall()]
        conn.close()
        if not sectors:
            return []

        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        digest = hashlib.sha256(day.encode()).hexdigest()
        change_idx = int(digest[:4], 16) % len(sectors)

        raw = []
        for i, sector in enumerate(sectors[:3]):
            raw.append({
                "sector": sector,
                "date": day,
                "cloud_cover_pct": (int(digest[4:6], 16) % 40),
                "change_detected": (i == change_idx),
                "change_area_ha": round((int(digest[6:8], 16) % 30) / 10.0, 1) if i == change_idx else 0,
                "confidence": round(0.6 + (int(digest[8:10], 16) % 35) / 100.0, 2) if i == change_idx else None,
            })
        return raw

    def normalize_data(self, raw_records: list[dict]) -> list[dict]:
        normalized = []
        for r in raw_records:
            normalized.append({
                "entity_type": "SatelliteScene",
                "external_id": f"sentinel-demo:{r['sector']}:{r['date']}",
                "sector": r["sector"],
                "provider_name": "Sentinel-2 (Demo)",
                "satellite": "Sentinel-2",
                "tier": TIER_1_BASELINE,
                "source_timestamp": r["date"],
                "cloud_cover_pct": r["cloud_cover_pct"],
                "resolution_m": 10.0,
                "cost_eur": None,
                "change_detected": r["change_detected"],
                "change_area_ha": r["change_area_ha"],
                "confidence": r["confidence"],
                "raw_payload": r,
            })
        return normalized

    def save_data(self, valid_records: list[dict]) -> dict:
        result = super().save_data(valid_records)
        for rec in valid_records:
            if rec.get("change_detected"):
                risk_rules.check_satellite_unregistered_change(rec, is_demo=True)
        return result
