"""
AI-generated operator recommendations for incidents (Stage 1b).

Same lazy Anthropic client pattern as services/robez_ocr_vision.py: init on
first use, raise if ANTHROPIC_API_KEY is missing. Unlike the OCR path, a
failure here must never break the caller (handle_location's geofence alert
flow) — generate_incident_recommendation() always returns a string or None,
never raises.
"""

import os

import anthropic

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


PROMPT_TEMPLATE = (
    "You are an operations assistant for a forestry company monitoring field "
    "workers via GPS. An incident was just detected. Here is what is known:\n\n"
    "Sector: {sector}\n"
    "Event: {reason}\n"
    "Entity type: {entity_type}\n"
    "Rule triggered: {rule_code}\n\n"
    "Based ONLY on the information given above (do not invent distances, "
    "durations, or any other numbers not provided), produce a detailed "
    "summary and 2-4 concrete response options for the dispatcher handling "
    "this incident. Each option needs a ready-to-send Telegram message to "
    "the worker — polite, specific, professional, in Russian, no markdown "
    "formatting, 2-3 sentences (not just one).\n\n"
    "Additionally, estimate a plausible financial exposure range in EUR for "
    "this specific incident, based on the type of violation described (e.g. "
    "lost/unaccounted timber value at typical market price ~€60-120/m³, "
    "equipment downtime cost, environmental fine risk, remediation cost for "
    "unauthorized infrastructure). Be explicit that this is an ESTIMATE, not "
    "a precise calculation. If the reason includes concrete volume/duration "
    "numbers, base the range on those; otherwise reason qualitatively from "
    "the violation type and severity (HIGH/MEDIUM). Keep the range realistic "
    "for a Latvian forestry operation.\n\n"
    "Also estimate the period over which this exposure accumulates if the "
    "situation is left unaddressed, based on the nature of the rule "
    "triggered ({rule_code}): a one-off discrepancy discovered after the "
    "fact (e.g. TIMBER_VOLUME_MISMATCH, TIMBER_UNEXPECTED_REMOVAL, "
    "STORM_DAMAGE) has a short, fixed assessment/remediation window; a "
    "stalled asset (e.g. EQUIPMENT_BREAKDOWN) accrues loss for as long as "
    "it stays unfixed; an ongoing unauthorized activity (e.g. "
    "UNAUTHORIZED_LOGGING, UNAUTHORIZED_FOREST_ROAD, "
    "ZONE_VIOLATION_TECHNOLOGY) keeps accruing loss daily until stopped. "
    "Phrase it as a short Russian phrase, e.g. 'в течение 2-4 недель' or "
    "'ежедневно, пока не устранено'.\n\n"
    "Return ONLY valid JSON, no markdown code fences, no explanation outside "
    "the JSON object, matching exactly this schema:\n\n"
    "{{\n"
    '  "summary": "A detailed paragraph (4-6 sentences) describing what happened, the context, and why it matters operationally — suitable for display on a supervisor'"'"'s dashboard during a live demo, in Russian, based ONLY on given data",\n'
    '  "options": [\n'
    '    {{"id": "contact_worker", "label": "Связаться с работником", "message_text": "..."}},\n'
    '    {{"id": "dispatch_supervisor", "label": "Направить супервайзера", "message_text": "..."}}\n'
    "  ],\n"
    '  "recommended_option_id": "contact_worker",\n'
    '  "estimated_exposure_eur_low": 1000,\n'
    '  "estimated_exposure_eur_high": 5000,\n'
    '  "exposure_basis": "Короткое (1 предложение) обоснование оценки на русском",\n'
    '  "exposure_period": "короткая фраза на русском о периоде накопления потерь, если ситуацию не исправить — например \'в течение 2-4 недель\' или \'ежедневно, пока не устранено\'"\n'
    "}}"
)


def generate_incident_recommendation(incident: dict) -> str:
    """
    incident: dict with at least sector, reason, entity_type, rule_code keys
    (the fields actually populated by database.add_incident()).
    Returns a JSON string ({"summary", "options", "recommended_option_id"}),
    or None on any failure (missing API key, API error, etc.) — errors are
    logged via print(), never raised, so a failure here never breaks the
    caller. Callers must be defensive when parsing: the model can still
    return malformed JSON.
    """
    prompt = PROMPT_TEMPLATE.format(
        sector=incident.get("sector") or "unknown",
        reason=incident.get("reason") or "unknown",
        entity_type=incident.get("entity_type") or "unknown",
        rule_code=incident.get("rule_code") or "unknown",
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()

        text = text.strip()
        if text.startswith("```"):
            # Strip a leading ```json / ``` fence and trailing ``` if present
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        return text or None
    except Exception as e:
        print(f"generate_incident_recommendation failed: {e}")
        return None
