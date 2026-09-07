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
    "durations, or any other numbers not provided), produce a short summary "
    "and 2-4 concrete response options for the dispatcher handling this "
    "incident. Each option needs a ready-to-send Telegram message to the "
    "worker (polite, specific, in Russian, no markdown formatting).\n\n"
    "Return ONLY valid JSON, no markdown code fences, no explanation outside "
    "the JSON object, matching exactly this schema:\n\n"
    "{{\n"
    '  "summary": "1-2 sentences describing what happened, in Russian, based ONLY on given data",\n'
    '  "options": [\n'
    '    {{"id": "contact_worker", "label": "Связаться с работником", "message_text": "..."}},\n'
    '    {{"id": "dispatch_supervisor", "label": "Направить супервайзера", "message_text": "..."}}\n'
    "  ],\n"
    '  "recommended_option_id": "contact_worker"\n'
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
            max_tokens=1024,
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
        return text or None
    except Exception as e:
        print(f"generate_incident_recommendation failed: {e}")
        return None
