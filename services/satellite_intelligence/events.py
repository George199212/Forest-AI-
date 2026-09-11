"""
Event-based triggers — one explicit function per trigger listed in the spec,
not a generic hook. Each function encodes its own stated firing condition
(a significance threshold, an "already flagged" requirement, a plausibility
check) directly in its signature/logic, so whether it escalates is inspectable
by reading the function, not by tracing through shared branching elsewhere.

Every trigger that is escalation-worthy on its own creates an incident via
database.add_incident() — the SAME table/lifecycle every other incident in
Forest AI already goes through (OPEN -> NOTIFIED -> RESOLVED/DISMISSED,
dispatcher-visible, eligible for an AI Inspector recommendation), using
entity_type="SATELLITE" (a new but consistent value on that already-free-text
column — not a new overload of the risks table's dual-purpose pattern, the
same way EMPLOYEE/VEHICLE/EQUIPMENT already coexist there). Per CODING_RULES.md
("never promote an AI score directly to a confirmed finding without a human
decision step"), creating the incident is NOT the same as confirming it — it
still starts OPEN and goes through the existing dispatcher workflow like any
other incident. rule_code values reuse the exact vocabulary already anticipated
in services/ai_resolution.py's prompt (STORM_DAMAGE, UNAUTHORIZED_LOGGING,
UNAUTHORIZED_FOREST_ROAD, TIMBER_VOLUME_MISMATCH, ZONE_VIOLATION_TECHNOLOGY)
where one exists, so the exposure-period reasoning already built into that
prompt template applies unchanged.

Each incident that gets created here also gets a recommendation from the
EXACT same pipeline every other Forest AI incident uses
(services/ai_resolution.py's generate_incident_recommendation(), via
inspector_bridge.attach_satellite_recommendation()) — with satellite evidence
folded in as extra context, not a second recommendation engine.
"""

import database
from .decision_engine import decide_and_request
from .risk_score import BAND_MEDIUM, BAND_HIGH, BAND_CRITICAL
from .inspector_bridge import attach_satellite_recommendation


def _create_satellite_incident(sector_name, rule_code, reason, risk_level, request=None, score_result=None):
    incident_id = database.add_incident(
        sector=sector_name, risk_level=risk_level, reason=reason,
        entity_type="SATELLITE", entity_id=None, rule_code=rule_code,
    )
    database.add_risk_event(incident_id, "DETECTED", actor="satellite_intelligence", details=reason)
    if request:
        database.link_satellite_request_incident(request["id"], incident_id)
    database.add_satellite_timeline_event(
        sector_name, "TRIGGER", label=f"Incident #{incident_id} created ({rule_code})",
        detail=reason, ref_table="risks", ref_id=incident_id,
    )
    # Same recommendation pipeline every other incident type uses — never
    # raises, so a failure here (e.g. no ANTHROPIC_API_KEY) never blocks
    # incident creation; the incident still lands OPEN for a dispatcher.
    attach_satellite_recommendation(
        incident_id, sector_name, reason, entity_type="SATELLITE", rule_code=rule_code,
        request=request, score_result=score_result,
    )
    return incident_id


def trigger_storm(sector_name, sector_center, affected_area_ha, ndvi_change_pct=None,
                   significance_threshold_ha=0.5, planetscope_configured=False):
    """Storm -> Sentinel before/after comparison -> if affected polygon is
    significant -> escalate. Below the significance threshold this still logs
    a normal Level-1 score (so the before/after comparison itself is on
    record) but does not treat it as a storm anomaly or create an incident."""
    significant = affected_area_ha is not None and affected_area_ha >= significance_threshold_ha
    signals = {"affected_area_ha": affected_area_ha}
    if significant:
        signals["storm_event"] = True
        if ndvi_change_pct is not None:
            signals["ndvi_change_pct"] = ndvi_change_pct

    decision = decide_and_request(sector_name, signals=signals, sector_center=sector_center,
                                   planetscope_configured=planetscope_configured)

    if not significant:
        return {"fired": False, "reason": f"Affected area {affected_area_ha} ha below "
                f"significance threshold ({significance_threshold_ha} ha) — no escalation.",
                "decision": decision, "incident_id": None}

    reason = f"Storm damage indicators over {affected_area_ha:.1f} ha (Sentinel before/after comparison)."
    request = decision.get("request")
    incident_id = _create_satellite_incident(
        sector_name, "STORM_DAMAGE", reason,
        "HIGH" if decision["score_result"]["band"] in (BAND_HIGH, BAND_CRITICAL) else "MEDIUM",
        request=request, score_result=decision["score_result"],
    )
    return {"fired": True, "reason": reason, "decision": decision, "incident_id": incident_id}


def trigger_fire(sector_name, sector_center, cloud_cover_pct=None, night=False,
                  planetscope_configured=False):
    """Fire -> thermal/burn detection -> ICEYE if cloud/night/urgent, SkySat
    once optical is viable. Fire is inherently urgent — floored to at least
    HIGH regardless of the generic weighted score."""
    signals = {"fire_event": True, "cloud_cover_pct": cloud_cover_pct, "night": night}
    decision = decide_and_request(sector_name, signals=signals, sector_center=sector_center,
                                   planetscope_configured=planetscope_configured, min_band=BAND_HIGH)

    reason = "Thermal/burn signature detected."
    request = decision.get("request")
    incident_id = _create_satellite_incident(
        sector_name, "FIRE_DAMAGE", reason, "HIGH",
        request=request, score_result=decision["score_result"],
    )
    return {"fired": True, "reason": reason, "decision": decision, "incident_id": incident_id}


def trigger_suspected_illegal_logging(sector_name, sector_center, ndvi_change_pct, cloud_cover_pct=None,
                                       ai_detection_confidence=None, planetscope_configured=False):
    """Suspected illegal logging -> Sentinel change detection -> Risk Score ->
    SkySat verification -> AI Inspector. Floored to at least HIGH: a
    clear-cut-shaped vegetation loss outside an approved cutting plan is
    inherently serious enough to warrant high-res verification, whatever the
    raw weighted score comes out to."""
    signals = {
        "suspected_clear_cut": True,
        "ndvi_change_pct": ndvi_change_pct,
        "cloud_cover_pct": cloud_cover_pct,
        "ai_detection_confidence": ai_detection_confidence,
    }
    decision = decide_and_request(sector_name, signals=signals, sector_center=sector_center,
                                   planetscope_configured=planetscope_configured, min_band=BAND_HIGH)

    reason = (f"Sentinel change detection: {abs(ndvi_change_pct):.0f}% vegetation loss consistent with "
              f"unauthorized clear-cutting.")
    request = decision.get("request")
    incident_id = _create_satellite_incident(
        sector_name, "UNAUTHORIZED_LOGGING", reason, "HIGH",
        request=request, score_result=decision["score_result"],
    )
    return {"fired": True, "reason": reason, "decision": decision, "incident_id": incident_id}


def trigger_new_road(sector_name, sector_center, cloud_cover_pct=None, ai_detection_confidence=None,
                      planetscope_configured=False):
    """New road -> new linear feature detected -> PlanetScope/SkySat
    verification. Floored to at least MEDIUM (guaranteeing at least a Level 2
    look) — a genuinely new linear feature always deserves verification even
    when no other anomaly signal is present."""
    signals = {
        "new_road_detected": True,
        "cloud_cover_pct": cloud_cover_pct,
        "ai_detection_confidence": ai_detection_confidence,
    }
    decision = decide_and_request(sector_name, signals=signals, sector_center=sector_center,
                                   planetscope_configured=planetscope_configured, min_band=BAND_MEDIUM)

    reason = "New linear feature detected, consistent with an unauthorized forest road."
    request = decision.get("request")
    incident_id = _create_satellite_incident(
        sector_name, "UNAUTHORIZED_FOREST_ROAD", reason, "MEDIUM",
        request=request, score_result=decision["score_result"],
    )
    return {"fired": True, "reason": reason, "decision": decision, "incident_id": incident_id}


def trigger_machinery_anomaly(sector_name, sector_center, already_flagged_incident_id,
                               cloud_cover_pct=None, planetscope_configured=False):
    """Machinery activity (from GPS/Telegram check-ins) -> compare before/after
    imagery ONLY if an anomaly is already flagged, not automatically. This
    function does not create a new incident — it attaches satellite
    verification to one that already exists (`already_flagged_incident_id`),
    same as the illegal-logging trigger attaches SkySat confirmation to a
    Sentinel-detected anomaly."""
    if not already_flagged_incident_id:
        return {"fired": False, "reason": "No anomaly already flagged — machinery presence alone "
                "does not trigger a satellite request.", "decision": None, "incident_id": None}

    signals = {"machinery_detected": True, "cloud_cover_pct": cloud_cover_pct}
    decision = decide_and_request(sector_name, signals=signals, sector_center=sector_center,
                                   planetscope_configured=planetscope_configured)

    request = decision.get("request")
    if request:
        database.link_satellite_request_incident(request["id"], already_flagged_incident_id)
    reason = f"Before/after imagery requested to verify already-flagged incident #{already_flagged_incident_id}."
    database.add_satellite_timeline_event(
        sector_name, "TRIGGER", label="Machinery anomaly verification",
        detail=reason, ref_table="risks", ref_id=already_flagged_incident_id,
    )
    return {"fired": True, "reason": reason, "decision": decision, "incident_id": already_flagged_incident_id}


def trigger_timber_shortage(sector_name, sector_center, planned_volume, actual_volume,
                             mismatch_threshold_pct=10.0, planetscope_configured=False):
    """Timber shortage (mismatch between timber_movements and expected volume)
    -> create investigation risk -> satellite verification of the relevant
    sector. Only fires past the mismatch threshold."""
    if not planned_volume:
        return {"fired": False, "reason": "No planned volume to compare against.",
                "decision": None, "incident_id": None}
    mismatch_pct = (planned_volume - actual_volume) / planned_volume * 100.0
    if mismatch_pct < mismatch_threshold_pct:
        return {"fired": False, "reason": f"Mismatch {mismatch_pct:.1f}% below threshold "
                f"({mismatch_threshold_pct}%) — no investigation needed.",
                "decision": None, "incident_id": None}

    decision = decide_and_request(sector_name, signals={}, sector_center=sector_center,
                                   planetscope_configured=planetscope_configured, min_band=BAND_MEDIUM)

    reason = (f"Timber volume mismatch: planned {planned_volume:.1f} m³ vs actual {actual_volume:.1f} m³ "
              f"({mismatch_pct:.1f}% shortfall) — satellite verification requested to check for "
              f"unrecorded removal.")
    request = decision.get("request")
    incident_id = _create_satellite_incident(
        sector_name, "TIMBER_VOLUME_MISMATCH", reason,
        "HIGH" if mismatch_pct >= 25 else "MEDIUM",
        request=request, score_result=decision["score_result"],
    )
    return {"fired": True, "reason": reason, "decision": decision, "incident_id": incident_id}


def trigger_contractor_outside_boundary(sector_name, sector_center, activity_plausible, distance_m=None,
                                         planetscope_configured=False):
    """Contractor GPS outside assigned sector boundary -> satellite
    verification ONLY if physical activity is plausible (e.g. a sustained
    excursion with movement, not one noisy GPS ping) — the plausibility
    judgment itself is made by the caller (the existing geofence logic in
    bot.py already tracks dwell time/distance) and passed in explicitly."""
    if not activity_plausible:
        return {"fired": False, "reason": "GPS excursion not plausible as physical activity "
                "(likely GPS noise) — no satellite verification requested.",
                "decision": None, "incident_id": None}

    signals = {"contractor_activity_outside_boundary": True}
    decision = decide_and_request(sector_name, signals=signals, sector_center=sector_center,
                                   planetscope_configured=planetscope_configured)

    dist_txt = f" ({distance_m:.0f}m from boundary)" if distance_m is not None else ""
    reason = f"Contractor GPS activity outside the assigned sector boundary{dist_txt} — satellite verification requested."
    request = decision.get("request")
    incident_id = _create_satellite_incident(
        sector_name, "ZONE_VIOLATION_TECHNOLOGY", reason, "MEDIUM",
        request=request, score_result=decision["score_result"],
    )
    return {"fired": True, "reason": reason, "decision": decision, "incident_id": incident_id}
