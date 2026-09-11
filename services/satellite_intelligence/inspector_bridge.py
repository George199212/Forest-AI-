"""
Bridges the Satellite Intelligence Engine into Forest AI's TWO existing AI
recommendation pipelines. Extends both, replaces neither — per spec, "do not
build a second, separate recommendation engine".

  1. services/ai_resolution.py's generate_incident_recommendation() — the
     per-incident recommendation engine (dispatcher options, ready-to-send
     Telegram messages, financial exposure estimate). build_satellite_context()
     produces the `satellite_context` string that function now optionally
     accepts; attach_satellite_recommendation() calls it exactly the way
     api.py's inspector_report_issue() already does for equipment-sourced
     incidents (generate -> set_ai_recommendation -> add_risk_event).

  2. api.py's streaming AI Inspector (_collect_sector_inspector_data() /
     INSPECTOR_PROMPT_TEMPLATE) — the sector-wide analysis endpoint.
     collect_satellite_inspector_fields() returns the extra keys api.py merges
     into that function's returned dict, so satellite monitoring status
     becomes one more input alongside risk_score, equipment, GPS, timber —
     all already collected there.
"""

import json

import database


def _inputs_dict(score_result: dict):
    """score_result may be the in-memory dict from risk_score.py (an
    `inputs` dict) or a DB row from sector_satellite_scores (an
    `inputs_json` string) — normalize either into a dict."""
    if not score_result:
        return None
    inputs = score_result.get("inputs")
    if inputs is None:
        raw = score_result.get("inputs_json")
        if raw:
            try:
                inputs = json.loads(raw)
            except (TypeError, ValueError):
                inputs = None
    return inputs if isinstance(inputs, dict) else None


def build_satellite_context(sector_name: str, request: dict = None, score_result: dict = None) -> str:
    """Human-readable evidence block for a satellite-triggered incident —
    passed as incident["satellite_context"] to generate_incident_recommendation().
    Falls back to the sector's latest stored score when score_result isn't
    given explicitly (e.g. called later, outside the original trigger call)."""
    if score_result is None:
        score_result = database.get_latest_satellite_score(sector_name)
    if not score_result:
        return ""

    lines = [
        f"- Satellite Monitoring Score: {score_result.get('score')} ({score_result.get('band')}) — "
        f"a distinct, satellite-specific score, separate from the sector's operational risk score above."
    ]

    inputs = _inputs_dict(score_result)
    if inputs:
        signal_bits = []
        if inputs.get("ndvi_change_pct") is not None:
            signal_bits.append(f"NDVI change {inputs['ndvi_change_pct']}%")
        if inputs.get("suspected_clear_cut"):
            signal_bits.append("suspected clear-cut pattern")
        if inputs.get("new_road_detected"):
            signal_bits.append("new linear feature (road)")
        if inputs.get("sar_change_detected"):
            signal_bits.append("SAR backscatter change")
        if inputs.get("storm_event"):
            signal_bits.append("storm damage indicators")
        if inputs.get("fire_event"):
            signal_bits.append("thermal/burn signature")
        if inputs.get("contractor_activity_outside_boundary"):
            signal_bits.append("contractor GPS activity outside boundary")
        if inputs.get("machinery_detected"):
            signal_bits.append("unexpected machinery presence")
        if inputs.get("cloud_cover_pct") is not None:
            signal_bits.append(f"cloud cover {inputs['cloud_cover_pct']}%")
        if inputs.get("ai_detection_confidence") is not None:
            signal_bits.append(f"AI detection confidence {inputs['ai_detection_confidence']:.0%}")
        if signal_bits:
            lines.append(f"- Detected signals: {', '.join(signal_bits)}")

    if request:
        lines.append(
            f"- Imagery requested: {request.get('provider')} (tier {request.get('tier')}), "
            f"estimated cost €{request.get('estimated_cost_eur')}, AOI {request.get('aoi_area_ha')} ha"
        )
        if request.get("justification"):
            lines.append(f"- Justification for ordering this imagery: {request['justification']}")

    return "\n".join(lines)


def attach_satellite_recommendation(incident_id: int, sector_name: str, reason: str, entity_type: str,
                                     rule_code: str, request: dict = None, score_result: dict = None):
    """Generate and store an AI Inspector recommendation for a
    satellite-triggered incident, through the SAME function every other
    incident type already uses — mirrors api.py's inspector_report_issue()
    (generate -> set_ai_recommendation -> add_risk_event). Never raises
    (generate_incident_recommendation() already guarantees that); returns the
    recommendation JSON string, or None on failure."""
    from services.ai_resolution import generate_incident_recommendation

    satellite_context = build_satellite_context(sector_name, request=request, score_result=score_result)
    recommendation = generate_incident_recommendation({
        "sector": sector_name, "reason": reason, "entity_type": entity_type,
        "rule_code": rule_code, "satellite_context": satellite_context,
    })
    if recommendation:
        database.set_ai_recommendation(incident_id, recommendation)
        database.add_risk_event(incident_id, "AI_RECOMMENDATION_GENERATED", actor="ai_satellite_intelligence")
    return recommendation


def collect_satellite_inspector_fields(sector_name: str) -> dict:
    """Extra keys merged into api.py's _collect_sector_inspector_data() output
    for the sector-wide streaming AI Inspector — satellite monitoring status
    as one more input, alongside risk_score/equipment/GPS/timber (already
    collected there). Returns {} when there's nothing satellite-related on
    record for this sector yet, so it adds no noise to sectors that have never
    triggered the engine."""
    latest_score = database.get_latest_satellite_score(sector_name)
    pending = database.get_satellite_requests(sector=sector_name, approval_status="PENDING", limit=5)
    recent_obs = database.get_satellite_observations(sector=sector_name, limit=3)
    if not latest_score and not pending and not recent_obs:
        return {}
    return {
        "satellite_monitoring_score": latest_score.get("score") if latest_score else None,
        "satellite_monitoring_band": latest_score.get("band") if latest_score else None,
        "satellite_pending_requests": [
            {"provider": r["provider"], "tier": r["tier"], "justification": r["justification"],
             "estimated_cost_eur": r["estimated_cost_eur"]}
            for r in pending
        ],
        "satellite_recent_observations": [
            {"provider": o["provider"], "tier": o["tier"], "acquisition_date": o["acquisition_date"],
             "cloud_cover_pct": o["cloud_cover_pct"]}
            for o in recent_obs
        ],
    }
