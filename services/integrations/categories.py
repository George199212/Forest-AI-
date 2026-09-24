"""
Category base classes over IntegrationAdapter — one per external-system
family from the spec. Each sets `category` and documents which normalized
entities and existing Forest AI domain table(s) it feeds. Concrete adapters
(demo/*.py today; real vendor adapters in later stages) subclass the
relevant category, not IntegrationAdapter directly.

None of these introduce a parallel data model: wherever Forest AI already
has a domain table for the entity (sectors, sector_equipment,
vehicle_gps_pings, timber_movements, satellite_observations,
weighbridge_records), the category's save_data() writes there in addition
to the generic integration_records staging row the base class always
writes — so existing pages (Sectors, GPS, Timber, Satellite) pick up
integration data automatically, with no separate "integrations" views
required on those pages.
"""

from datetime import datetime

import database
from .base import IntegrationAdapter


class MachineIntegrationAdapter(IntegrationAdapter):
    """Harvesters/forwarders — PONSSE Manager, John Deere TimberMatic/
    TimberManager, Komatsu Smart Forestry/MaxiFleet/MaxiVision. Normalized
    entities: Machine, MachineEvent. Feeds sector_equipment (status/fuel/
    working hours) by matching equipment_code."""
    category = "machine"


class FleetIntegrationAdapter(IntegrationAdapter):
    """GPS/telematics for trucks and heavy equipment — ZF SCALAR, timber
    truck GPS, fuel control, e-waybills. Normalized entities: Vehicle,
    GPSPosition, RoutePoint, TimberMovement. Feeds vehicle_gps_pings via
    database.add_gps_ping()."""
    category = "fleet"

    def save_data(self, valid_records: list[dict]) -> dict:
        result = super().save_data(valid_records)
        for rec in valid_records:
            if rec.get("entity_type") != "GPSPosition":
                continue
            lat, lon = rec.get("latitude"), rec.get("longitude")
            if lat is None or lon is None:
                continue
            database.add_gps_ping(
                entity_type=rec.get("gps_entity_type", "VEHICLE"),
                entity_id=rec.get("vehicle_id") or rec.get("external_id"),
                sector=rec.get("sector") or "",
                latitude=lat, longitude=lon,
                inside_boundary=rec.get("inside_boundary", 1),
            )
        return result


class GISIntegrationAdapter(IntegrationAdapter):
    """Boundaries and maps — LVM GEO, corporate GIS, GNSS/RTK GNSS,
    GeoJSON/KML/GPX/Shapefile import, cadastral data. Normalized entity:
    GeoZone. Stage 1: staged in integration_records only — writing sector
    boundaries automatically is a human-reviewed action (stage 2 GeoJSON/
    KML import flow), not an unattended sync."""
    category = "gis"


class SatelliteIntegrationAdapter(IntegrationAdapter):
    """Sentinel-1/2, Landsat, PlanetScope, SkySat, Maxar, ICEYE. Wraps the
    existing services/satellite_intelligence package rather than
    duplicating it — see demo/sentinel_demo.py. Normalized entities:
    SatelliteScene, SatelliteChange. Feeds satellite_observations via
    database.add_satellite_observation()."""
    category = "satellite"

    def save_data(self, valid_records: list[dict]) -> dict:
        result = super().save_data(valid_records)
        for rec in valid_records:
            if rec.get("entity_type") != "SatelliteScene":
                continue
            database.add_satellite_observation(
                sector=rec.get("sector"), provider=rec.get("provider_name", self.provider),
                tier=rec.get("tier", "1"), satellite=rec.get("satellite"),
                acquisition_date=rec.get("source_timestamp"),
                resolution_m=rec.get("resolution_m"), cloud_cover_pct=rec.get("cloud_cover_pct"),
                bbox=rec.get("bbox"), image_id=rec.get("external_id"),
                image_ref=rec.get("image_ref"), source="DEMO" if self.is_demo else "LIVE",
                cost_eur=rec.get("cost_eur"), risk_score=rec.get("risk_score"),
            )
        return result


class TimberIntegrationAdapter(IntegrationAdapter):
    """Timber accounting / inventory systems, e-waybills. Normalized
    entities: TimberMovement, TimberInventory. Stage 1: staged in
    integration_records; stage 2 adds CSV/API import writing
    timber_movements directly (same shape api.py's existing timber routes
    already read)."""
    category = "timber"


class WeighbridgeIntegrationAdapter(IntegrationAdapter):
    """Weighbridge/scale systems, warehouse systems. Normalized entity:
    WeighbridgeRecord. Feeds the new weighbridge_records table via
    database.add_weighbridge_record()."""
    category = "weighbridge"

    def save_data(self, valid_records: list[dict]) -> dict:
        result = super().save_data(valid_records)
        for rec, linked_id in zip(valid_records, result.get("linked_ids", [])):
            if rec.get("entity_type") != "WeighbridgeRecord":
                continue
            database.add_weighbridge_record(
                sector=rec.get("sector"), vehicle_plate=rec.get("vehicle_plate"),
                driver=rec.get("driver"), trip_number=rec.get("trip_number"),
                destination=rec.get("destination"), species=rec.get("species"),
                assortment=rec.get("assortment"), weighed_at=rec.get("source_timestamp"),
                weight_gross_kg=rec.get("weight_gross_kg"), weight_tare_kg=rec.get("weight_tare_kg"),
                declared_volume_m3=rec.get("declared_volume_m3"),
                actual_volume_m3=rec.get("actual_volume_m3"),
                document_number=rec.get("document_number"), photo_path=rec.get("photo_path"),
                acceptance_status=rec.get("acceptance_status", "PENDING"),
                integration_id=self.integration_id, is_demo=self.is_demo,
                source_record_id=linked_id,
            )
        return result


class WorkerIntegrationAdapter(IntegrationAdapter):
    """Telegram bot/live, worker smartphone GPS, mobile photo capture,
    check-in/out. Normalized entities: Worker, WorkSession, WorkPhoto.
    Stage 1: staged in integration_records only — bot.py's existing
    check-in/live-location flow remains the sole writer of work_sessions/
    live_locations; this category exists so future non-Telegram worker
    apps have a defined integration point without touching bot.py."""
    category = "worker"


class ERPIntegrationAdapter(IntegrationAdapter):
    """Company ERP / internal systems. No dedicated normalized entity yet —
    staged in integration_records for downstream mapping per client."""
    category = "erp"


class AuditIntegrationAdapter(IntegrationAdapter):
    """Forest audit systems — TIMBRO (LiDAR, GNSS, cameras, inventory
    algorithms). Normalized entity: AuditMeasurement. Stage 1: staged in
    integration_records only; TIMBRO's actual provider/API is unconfirmed
    (see registry.py), so no domain table write is implemented yet."""
    category = "audit"
