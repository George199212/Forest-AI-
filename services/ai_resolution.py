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
    "Write a short recommendation (3-5 sentences, in Russian) for the dispatcher "
    "handling this incident: briefly state what happened based ONLY on the "
    "information given above (do not invent distances, durations, or any other "
    "numbers not provided), what action the dispatcher should take next, and "
    "the priority/urgency of that action. Do not use markdown formatting."
)


def generate_incident_recommendation(incident: dict) -> str:
    """
    incident: dict with at least sector, reason, entity_type, rule_code keys
    (the fields actually populated by database.add_incident()).
    Returns the recommendation text, or None on any failure (missing API key,
    API error, etc.) — errors are logged via print(), never raised, so a
    failure here never breaks the caller.
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
            max_tokens=512,
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
