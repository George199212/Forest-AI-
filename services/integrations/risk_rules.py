"""
Integration Layer -> Risk Engine bridge.

Not a second risk engine: every rule here ends in the exact same call
bot.py's live geofence flow and services/demo_scenarios.py already use —
database.add_incident() (same `risks` table, same OPEN/NOTIFIED/RESOLVED
lifecycle) followed by generate_incident_recommendation() ->
set_ai_recommendation(). Dedup uses database.get_active_incident_by_rule(),
the generalized form of the inline check bot.py already does for
SECTOR_EXIT/EMERGENCY, so a repeated sync/webhook never spams duplicate
incidents for the same ongoing condition.

Stage 1 wires the rules reachable by the three implemented demo adapters:

  - fleet_gps  -> FLEET_SECTOR_EXIT        (scenario: vehicle/equipment left its permitted sector)
  - satellite  -> SATELLITE_UNREGISTERED_CHANGE  (scenario: change detected with no registered work)
  - weighbridge-> WEIGHBRIDGE_WAYBILL_MISMATCH   (scenario: scale weight vs waybill volume disagree)
  - weighbridge-> TIMBER_VOLUME_OVER_PERMIT      (scenario: hauled volume exceeds the sector's approved volume)

The remaining scenarios in the spec (worker sector exit, wetland proximity,
machine breakdown, prolonged idle, route deviation, off-sector check-in/
photo, cross-source contradiction) need normalized data from categories not
yet backed by a stage-1 demo adapter (worker, machine, GIS zones) — the
functions are not stubbed here to avoid dead code; they get added in the
same category adapter's save_data() when that adapter is implemented,
following this exact pattern.
"""

import json
import re

import database
from services import geo
from services.ai_resolution import generate_incident_recommendation

# Rule codes raised per integration category — used by manager.reset_demo()
# to scope "Reset Demo Data" to exactly the incidents one integration
# created, never another demo integration's incidents in the same category
# list.
RULE_CODES_BY_CATEGORY = {
    "fleet": ["FLEET_SECTOR_EXIT"],
    "satellite": ["SATELLITE_UNREGISTERED_CHANGE"],
    "weighbridge": ["WEIGHBRIDGE_WAYBILL_MISMATCH", "TIMBER_VOLUME_OVER_PERMIT"],
}


def _ai_recommendation(incident_id, sector, reason, entity_type, rule_code):
    recommendation = generate_incident_recommendation({
        "sector": sector, "reason": reason, "entity_type": entity_type, "rule_code": rule_code,
    })
    if not recommendation:
        recommendation = json.dumps({
            "summary": reason,
            "options": [],
            "recommended_option_id": None,
            "estimated_exposure_eur_low": None,
            "estimated_exposure_eur_high": None,
            "exposure_basis": "AI recommendation unavailable — integration event logged without estimate.",
        }, ensure_ascii=False)
        actor = "ai_fallback"
    else:
        actor = "ai"
    database.set_ai_recommendation(incident_id, recommendation)
    database.add_risk_event(incident_id, "AI_RECOMMENDATION_GENERATED", actor=actor)


def _raise_or_continue_incident(sector, rule_code, entity_type, entity_id, reason, risk_level,
                                 is_demo, distance_m=None, still_event="STILL_ACTIVE"):
    existing = database.get_active_incident_by_rule(rule_code, entity_type=entity_type,
                                                      entity_id=entity_id, sector=sector)
    if existing:
        database.add_risk_event(existing["id"], still_event, actor="integration", details=reason)
        return existing["id"], False

    incident_id = database.add_incident(
        sector=sector, risk_level=risk_level, reason=reason,
        entity_type=entity_type, entity_id=entity_id, rule_code=rule_code, distance_m=distance_m,
    )
    if is_demo:
        database_update_is_demo(incident_id)
    database.add_risk_event(incident_id, "DETECTED", actor="integration", details=reason)
    _ai_recommendation(incident_id, sector, reason, entity_type, rule_code)
    return incident_id, True


def database_update_is_demo(incident_id):
    # add_incident() has no is_demo parameter (it's a shared function used
    # by every incident source, not just integrations) — flip the flag
    # right after insert instead of widening that function's signature.
    import sqlite3
    conn = sqlite3.connect(database.DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE risks SET is_demo=1 WHERE id=?", (incident_id,))
    conn.commit()
    conn.close()


def check_fleet_sector_exit(normalized_record: dict, is_demo: bool = False):
    """normalized_record: a GPSPosition entity (see categories.FleetIntegrationAdapter) —
    {sector, latitude, longitude, vehicle_id, gps_entity_type, external_id}.
    Compares against the sector's own boundary_json via geo.point_in_polygon,
    exactly the polygon check bot.py's handle_location() already uses."""
    sector_name = normalized_record.get("sector")
    lat, lon = normalized_record.get("latitude"), normalized_record.get("longitude")
    if not sector_name or lat is None or lon is None:
        return None
    sector_row = geo.get_sector_row(sector_name)
    if not sector_row or not sector_row.get("boundary_json"):
        return None
    boundary = json.loads(sector_row["boundary_json"])
    if not boundary or geo.point_in_polygon(lat, lon, boundary):
        return None

    entity_type = normalized_record.get("gps_entity_type", "VEHICLE")
    entity_id = normalized_record.get("vehicle_id") or normalized_record.get("external_id")
    distance_m = geo.distance_to_polygon_edge_m(lat, lon, boundary)
    reason = f"{entity_type.title()} {entity_id} left the boundary of sector {sector_name} (GPS)."
    incident_id, created = _raise_or_continue_incident(
        sector_name, "FLEET_SECTOR_EXIT", entity_type, str(entity_id), reason, "HIGH",
        is_demo, distance_m=distance_m, still_event="STILL_OUTSIDE",
    )
    return incident_id


def check_satellite_unregistered_change(normalized_record: dict, is_demo: bool = False):
    """normalized_record: a SatelliteChange-shaped entity —
    {sector, change_detected: bool, change_area_ha, confidence, external_id}.
    Flags a change with no corresponding recent timber_movements activity in
    that sector — scenario 8 in the spec ("satellite change without
    registered works")."""
    sector_name = normalized_record.get("sector")
    if not sector_name or not normalized_record.get("change_detected"):
        return None
    recent_work = database.db1_raw(
        "SELECT COUNT(*) AS n FROM timber_movements WHERE sector=? "
        "AND created_at >= datetime('now', '-14 days')", (sector_name,)
    )
    if recent_work and recent_work.get("n"):
        return None

    area = normalized_record.get("change_area_ha")
    confidence = normalized_record.get("confidence")
    reason = (
        f"Satellite change detected in sector {sector_name} "
        f"({area or '?'} ha, confidence {confidence or '?'}) with no registered timber "
        f"movements in the last 14 days."
    )
    incident_id, created = _raise_or_continue_incident(
        sector_name, "SATELLITE_UNREGISTERED_CHANGE", "SATELLITE",
        normalized_record.get("external_id", sector_name), reason, "HIGH", is_demo,
        still_event="STILL_UNEXPLAINED",
    )
    return incident_id


def check_weighbridge_waybill_mismatch(normalized_record: dict, is_demo: bool = False,
                                        tolerance_pct: float = 10.0):
    """normalized_record: a WeighbridgeRecord entity —
    {sector, declared_volume_m3, actual_volume_m3, trip_number, external_id}.
    actual_volume_m3 here is the volume computed from the scale's net weight;
    declared_volume_m3 is what the waybill claims."""
    sector_name = normalized_record.get("sector")
    declared = normalized_record.get("declared_volume_m3")
    actual = normalized_record.get("actual_volume_m3")
    if not sector_name or declared in (None, 0) or actual is None:
        return None
    diff_pct = abs(actual - declared) / declared * 100.0
    if diff_pct <= tolerance_pct:
        return None

    reason = (
        f"Weighbridge net volume ({actual:.1f} m³) differs from the waybill-declared volume "
        f"({declared:.1f} m³) by {diff_pct:.0f}% for trip {normalized_record.get('trip_number', '?')}."
    )
    incident_id, created = _raise_or_continue_incident(
        sector_name, "WEIGHBRIDGE_WAYBILL_MISMATCH", "TIMBER",
        normalized_record.get("trip_number") or normalized_record.get("external_id"), reason,
        "MEDIUM" if diff_pct < 25 else "HIGH", is_demo,
    )
    return incident_id


def check_volume_over_permit(sector_name: str, is_demo: bool = False):
    """Sums actual_volume_m3 across weighbridge_records for this sector and
    compares against sectors.approved_volume (existing free-text/numeric
    field). Scenario 9 in the spec."""
    sector_row = geo.get_sector_row(sector_name)
    if not sector_row:
        return None
    # approved_volume is a free-text field elsewhere in the app (seen as
    # both "600 m3" and plain "150") — extract the leading numeric portion
    # rather than assuming either shape.
    match = re.search(r"[\d.,]+", str(sector_row.get("approved_volume") or ""))
    if not match:
        return None
    try:
        approved = float(match.group(0).replace(",", "."))
    except ValueError:
        return None
    if approved <= 0:
        return None

    total = database.db1_raw(
        "SELECT COALESCE(SUM(actual_volume_m3), 0) AS v FROM weighbridge_records WHERE sector=?",
        (sector_name,),
    )
    hauled = total["v"] if total else 0
    if hauled <= approved:
        return None

    reason = f"Hauled volume ({hauled:.1f} m³) exceeds the approved volume ({approved:.1f} m³) for sector {sector_name}."
    incident_id, created = _raise_or_continue_incident(
        sector_name, "TIMBER_VOLUME_OVER_PERMIT", "TIMBER", sector_name, reason, "HIGH", is_demo,
    )
    return incident_id
