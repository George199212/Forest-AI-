"""
Weighbridge Demo Adapter.

Fabricates deterministic synthetic weighbridge tickets (gross/tare/net
weight, declared vs actual volume) for one real sector per sync — no
network call, no real client scale data. One ticket per day is seeded to
disagree with its waybill-declared volume by more than the tolerance
(risk_rules.check_weighbridge_waybill_mismatch), demonstrating the
weighbridge-vs-waybill contradiction scenario; cumulative volume across
demo tickets can also exceed a sector's approved_volume
(risk_rules.check_volume_over_permit), demonstrating the over-permit
scenario — both against the exact same weighbridge_records table a real
CSV-import adapter (stage 2) would write into.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone

import database
from services.integrations import risk_rules
from services.integrations.categories import WeighbridgeIntegrationAdapter

WOOD_DENSITY_T_PER_M3 = 0.85  # rough green-timber density, demo only


class WeighbridgeDemoAdapter(WeighbridgeIntegrationAdapter):
    provider = "weighbridge_demo"
    display_name = "Weighbridge (Demo)"
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
                    "AND boundary_json != '' ORDER BY name LIMIT 3")
        sectors = [r["name"] for r in cur.fetchall()]
        conn.close()
        if not sectors:
            return []

        now = datetime.now(timezone.utc)
        bucket = now.strftime("%Y-%m-%dT%H:00:00Z")
        digest = hashlib.sha256(bucket.encode()).hexdigest()

        raw = []
        for i, sector in enumerate(sectors[:2]):
            trip_number = f"DEMO-TRIP-{i+1}-{now.strftime('%Y%m%d%H')}"
            gross_kg = 38000 + (int(digest[i * 4:i * 4 + 4], 16) % 4000)
            tare_kg = 14000
            net_kg = gross_kg - tare_kg
            actual_volume_m3 = round((net_kg / 1000.0) / WOOD_DENSITY_T_PER_M3, 1)
            # sector 0 is a clean match; sector 1 is seeded to disagree with
            # its waybill by ~30% to demonstrate the mismatch rule.
            declared_volume_m3 = actual_volume_m3 if i == 0 else round(actual_volume_m3 * 0.7, 1)
            raw.append({
                "sector": sector, "trip_number": trip_number,
                "vehicle_plate": f"DEMO-{101 + i}", "driver": "Demo driver",
                "weighed_at": bucket, "weight_gross_kg": gross_kg, "weight_tare_kg": tare_kg,
                "weight_net_kg": net_kg, "actual_volume_m3": actual_volume_m3,
                "declared_volume_m3": declared_volume_m3, "species": "Pine", "assortment": "Sawlog",
                "document_number": f"WB-{digest[:8]}-{i}",
            })
        return raw

    def normalize_data(self, raw_records: list[dict]) -> list[dict]:
        normalized = []
        for r in raw_records:
            normalized.append({
                "entity_type": "WeighbridgeRecord",
                "external_id": r["trip_number"],
                "sector": r["sector"],
                "trip_number": r["trip_number"],
                "vehicle_plate": r["vehicle_plate"],
                "driver": r["driver"],
                "source_timestamp": r["weighed_at"],
                "weight_gross_kg": r["weight_gross_kg"],
                "weight_tare_kg": r["weight_tare_kg"],
                "actual_volume_m3": r["actual_volume_m3"],
                "declared_volume_m3": r["declared_volume_m3"],
                "species": r["species"],
                "assortment": r["assortment"],
                "document_number": r["document_number"],
                "acceptance_status": "ACCEPTED",
                "raw_payload": r,
            })
        return normalized

    def save_data(self, valid_records: list[dict]) -> dict:
        result = super().save_data(valid_records)
        touched_sectors = set()
        for rec in valid_records:
            risk_rules.check_weighbridge_waybill_mismatch(rec, is_demo=True)
            touched_sectors.add(rec["sector"])
        for sector in touched_sectors:
            risk_rules.check_volume_over_permit(sector, is_demo=True)
        return result
