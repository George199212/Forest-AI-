"""Human CREATE_RISK -> existing Risk Engine (Stage 2, decisions D2/D3/D4). Runs in the API process only.

No automatic risks (config auto_risk_enabled = False): this module is called only from the review route, by an
authenticated user. It uses the EXISTING database.add_incident / add_risk_event / add_risk_evidence and the existing
AI recommendation call (services.ai_resolution.generate_incident_recommendation) - no second risk system.

Writes go to the main forest_ai.db through `database` (database.DB_NAME). In Stage 2 this runs only against TEST
COPIES; production forest_ai.db stays read-only until the Stage 4 release.

Idempotent: the risk is keyed by entity_type='SATELLITE', entity_id='sat_event:<id>'. If linking the risk back to
the event fails, a retry finds the same open risk instead of creating a second one.
"""
import json

from . import store

RULE_DURING_WORK = "SATELLITE_CHANGE_DURING_WORK"
RULE_UNREGISTERED = "SATELLITE_UNREGISTERED_CHANGE"
RISK_LEVEL = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
SOURCE_PROVIDER = "SATELLITE"
EVIDENCE_TYPE = "SATELLITE_CHANGE_EVENT"

TRUTH_RULES = (
    "Rules for this recommendation: the change is SUSPECTED, from automated Copernicus Sentinel analysis, and not "
    "verified on the ground. Use only the facts given above; do not invent causes, people, volumes or money. Do not "
    "call it illegal, a violation or a confirmed felling. Recommend verification steps (visual review of the images, "
    "a field check) before any other action."
)


def rule_code(ev):
    ctx = store._j(ev.get("gps_context_json"), {}) or {}
    return RULE_DURING_WORK if ctx.get("context_label") == "CHANGE_DURING_REGISTERED_WORK" else RULE_UNREGISTERED


def entity_id(ev):
    return f"sat_event:{ev['id']}"


def reason_text(ev, area):
    return (f"{store.event_summary(ev)} Satellite monitoring area '{area['name']}' ({area['source']} "
            f"{area['source_ref']}), event #{ev['id']}, observed {ev['first_after_time_utc'][:10]} .. "
            f"{ev['last_after_time_utc'][:10]}; detection confidence {ev['confidence']}, evidence quality "
            f"{ev['evidence_quality']}.")


def evidence_summary(ev):
    ctx = store._j(ev.get("gps_context_json"), {}) or {}
    split = store._j(ev.get("compartment_split_json"))
    parts = [f"sensor basis {ev['sensor_basis']}",
             f"changed {ev['changed_area_ha']:.2f} ha (inside {ev['changed_area_ha_inside']:.2f} ha, "
             f"outside the approved boundary {ev['changed_area_ha_buffer']:.2f} ha)",
             f"classification {ev['classification']} (automated, suspected)",
             f"confidence {ev['confidence']}, evidence quality {ev['evidence_quality']}",
             f"operational context {ctx.get('context_label', 'unknown')} "
             f"({ctx.get('activity_records', 'unknown')} registered records)"]
    if split and "unavailable" not in split:
        parts.append(f"VMD compartments: stand {split['stand_zkat10_ha']:.2f} ha, clear-cut land "
                     f"{split['clearcut_zkat14_ha']:.2f} ha, other {split['other_compartments_ha']:.2f} ha, none "
                     f"{split['no_compartment_ha']:.2f} ha")
    if ev.get("seasonal_caveat"):
        parts.append(f"seasonal caveat: {ev['seasonal_caveat']}")
    return "; ".join(parts) + ". Contains modified Copernicus Sentinel data."


def _find_existing(database, ev):
    for code in (RULE_UNREGISTERED, RULE_DURING_WORK):
        r = database.get_active_incident_by_rule(code, entity_type="SATELLITE", entity_id=entity_id(ev))
        if r:
            return r
    return None


def _ai(database, risk_id, area, reason, code, ev, recommend):
    rec = None
    try:
        rec = recommend({"sector": area["name"], "reason": reason, "entity_type": "SATELLITE", "rule_code": code,
                         "satellite_context": evidence_summary(ev), "extra_prompt_block": TRUTH_RULES})
    except Exception:                        # the risk exists either way; the AI step never breaks it
        rec = None
    if rec:
        actor = "ai"
    else:
        rec = json.dumps({"summary": reason, "options": [], "recommended_option_id": None,
                          "estimated_exposure_eur_low": None, "estimated_exposure_eur_high": None,
                          "exposure_basis": "AI recommendation unavailable - suspected satellite change logged "
                                            "without estimate."}, ensure_ascii=False)
        actor = "ai_fallback"
    database.set_ai_recommendation(risk_id, rec)
    database.add_risk_event(risk_id, "AI_RECOMMENDATION_GENERATED", actor=actor)


def create_risk(ev, area, actor, database=None, recommend=None):
    """Create (or find) the risk for a CURRENT event on a human request. Returns (risk_id, created)."""
    if not actor:
        raise store.StoreError(401, "authenticated user required")
    if ev.get("superseded_at_utc"):
        raise store.StoreError(409, "event was superseded by a later detection generation")
    if ev.get("risk_id") is not None:
        return ev["risk_id"], False
    if database is None:
        import database
    if recommend is None:
        from services.ai_resolution import generate_incident_recommendation as recommend
    existing = _find_existing(database, ev)
    if existing:
        return existing["id"], False
    code = rule_code(ev)
    reason = reason_text(ev, area)
    for w in store.FORBIDDEN_WORDS:                     # D4 guard
        if w in reason.lower():
            raise RuntimeError("non-neutral wording in risk reason")
    risk_id = database.add_incident(
        sector=area["name"], risk_level=RISK_LEVEL[ev["confidence"]], reason=reason, entity_type="SATELLITE",
        entity_id=entity_id(ev), rule_code=code, data_origin="REAL", occurred_at=ev["first_after_time_utc"])
    database.add_risk_event(risk_id, "SATELLITE_RISK_CREATED", actor=actor,
                            details=json.dumps({"source": "satellite_monitoring", "event_id": ev["id"],
                                                "area_id": area["id"], "requested_by": actor}))
    database.add_risk_evidence(risk_id, SOURCE_PROVIDER, "REAL", EVIDENCE_TYPE, evidence_summary(ev),
                               ref_table="sat_change_events", ref_id=ev["id"], observed_at=ev["last_after_time_utc"])
    _ai(database, risk_id, area, reason, code, ev, recommend)
    return risk_id, True


def note_review(risk_id, decision, actor, note, database=None):
    """REJECT (and the UNDO of a REJECT) on an event linked to a risk: an audit event on that SAME risk. The risk
    status stays with the existing workflow (never changed or deleted here)."""
    if risk_id is None:
        return None
    if database is None:
        import database
    return database.add_risk_event(risk_id, f"SATELLITE_REVIEW_{decision}", actor=actor, details=note)
