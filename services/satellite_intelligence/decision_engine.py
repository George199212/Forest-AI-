"""
Escalation logic: given a sector's satellite monitoring score (risk_score.py),
decide which tier is actually worth using right now, and — for a commercial
(Level 2/3) request — produce the cost-control bookkeeping the spec requires:
estimated_cost, reason, risk_score, requested_resolution, AOI_area,
provider, approval_status, and a stored human-readable justification string.

    NORMAL / WATCH  -> Level 1 only. No commercial request.
    MEDIUM          -> Level 2 (PlanetScope) if configured; otherwise flagged
                        for increased Level 1 frequency only — no request.
    HIGH / CRITICAL -> Level 3a (SkySat) if optical is viable, else Level 3b
                        (ICEYE). CRITICAL requests immediately; HIGH is allowed
                        to batch with nearby pending requests.

This module owns the DB writes for satellite_requests / sector_satellite_scores
/ satellite_timeline_events (via database.py's accessor functions — same
pattern api.py and bot.py already use, not a new convention).
"""

import math
from datetime import datetime

import database
from .models import TIER_1_BASELINE, TIER_2_FREQUENT, TIER_3A_OPTICAL_HIGHRES, TIER_3B_SAR_HIGHRES, TIER_LABELS
from .risk_score import compute_satellite_monitoring_score, BAND_NORMAL, BAND_WATCH, BAND_MEDIUM, BAND_HIGH, BAND_CRITICAL

# Illustrative planning-level cost estimates — NOT a live price quote from any
# provider (none of PlanetScope/SkySat/ICEYE are connected — see providers/
# commercial.py). Used only so the demo and the UI can show cost control
# actually working; replace with real pricing once a provider account exists.
COST_MODEL = {
    "planetscope": {"base_eur": 0.0,  "per_ha_eur": 1.5,  "min_resolution_m": 3.0},
    "skysat":      {"base_eur": 30.0, "per_ha_eur": 12.0, "min_resolution_m": 0.5},
    "iceye":       {"base_eur": 45.0, "per_ha_eur": 18.0, "min_resolution_m": 1.0},
}

# Above this cloud cover (%), optical high-res (SkySat) verification is not
# considered viable "right now" and the engine falls back to SAR (ICEYE).
CLOUD_COVER_OPTICAL_LIMIT = 50.0

# Nearby pending Level-3 requests within this radius get grouped into one AOI
# — "combine geographically close risks into one AOI where possible".
AOI_COMBINE_RADIUS_KM = 3.0

# An archive image younger than this is considered still useful — "check
# whether sufficient archive imagery already exists" before ordering new.
ARCHIVE_REUSE_MAX_AGE_DAYS = {
    TIER_2_FREQUENT: 5,
    TIER_3A_OPTICAL_HIGHRES: 3,
    TIER_3B_SAR_HIGHRES: 3,
}


def _haversine_km(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def optical_is_viable(cloud_cover_pct=None, night=False, urgent_all_weather=False) -> bool:
    """Explicit condition for the 3a-vs-3b choice — night or an explicit
    all-weather/rapid-confirmation requirement always forces SAR; otherwise
    it's a plain cloud-cover threshold."""
    if night or urgent_all_weather:
        return False
    if cloud_cover_pct is not None and cloud_cover_pct > CLOUD_COVER_OPTICAL_LIMIT:
        return False
    return True


def decide_tier(score_result: dict, cloud_cover_pct=None, night=False, urgent_all_weather=False,
                 planetscope_configured=False) -> dict:
    """Map a satellite_monitoring_score result to a tier decision. Pure
    function — no DB access, no side effects — so it's trivially unit-testable
    and reusable from both the orchestrator below and the demo seed.
    """
    band = score_result["band"]
    score = score_result["score"]

    if band in (BAND_NORMAL, BAND_WATCH):
        return {
            "tier": TIER_1_BASELINE, "provider": "sentinel2", "commercial": False,
            "immediate": False, "combinable": False,
            "reason": "Score below MEDIUM threshold — baseline monitoring only, no commercial request.",
        }

    if band == BAND_MEDIUM:
        if planetscope_configured:
            return {
                "tier": TIER_2_FREQUENT, "provider": "planetscope", "commercial": True,
                "immediate": False, "combinable": True,
                "reason": f"Score {score} (MEDIUM) — frequent monitoring via PlanetScope.",
            }
        return {
            "tier": TIER_1_BASELINE, "provider": "sentinel2", "commercial": False,
            "immediate": False, "combinable": False,
            "increase_frequency": True,
            "reason": f"Score {score} (MEDIUM) but PlanetScope is not configured — "
                      f"falling back to increased Level 1 (Sentinel) analysis frequency only.",
        }

    # HIGH or CRITICAL
    optical_ok = optical_is_viable(cloud_cover_pct, night, urgent_all_weather)
    if optical_ok:
        tier, provider = TIER_3A_OPTICAL_HIGHRES, "skysat"
        cloud_note = f"optical viable (cloud cover {cloud_cover_pct}%)" if cloud_cover_pct is not None else "optical viable"
    else:
        tier, provider = TIER_3B_SAR_HIGHRES, "iceye"
        if night:
            cloud_note = "night — optical unavailable"
        elif urgent_all_weather:
            cloud_note = "urgent/all-weather confirmation required"
        else:
            cloud_note = f"cloud cover {cloud_cover_pct}% exceeds optical limit ({CLOUD_COVER_OPTICAL_LIMIT}%)"

    return {
        "tier": tier, "provider": provider, "commercial": True,
        "immediate": band == BAND_CRITICAL,
        "combinable": band == BAND_HIGH,
        "reason": f"Score {score} ({band}) — {TIER_LABELS[tier]} requested, {cloud_note}.",
    }


def estimate_cost(tier: str, provider: str, aoi_area_ha: float) -> float:
    model = COST_MODEL.get(provider)
    if not model:
        return 0.0
    return round(model["base_eur"] + model["per_ha_eur"] * max(aoi_area_ha, 0.0), 2)


def build_justification(sector: str, score_result: dict, tier_decision: dict, aoi_area_ha: float,
                         provider_label: str) -> str:
    """Human-readable justification string — stored verbatim in
    satellite_requests.justification and shown in the UI as-is, per spec
    example: "SkySat requested because Sentinel-2 detected a 1.8 ha vegetation
    loss with Risk Score 82. High-resolution optical verification is required."
    """
    inputs = score_result["inputs"]
    score = score_result["score"]
    band = score_result["band"]
    area_txt = f"{aoi_area_ha:.1f} ha" if aoi_area_ha else "the affected area"

    trigger_bits = []
    if inputs.get("ndvi_change_pct") is not None and inputs["ndvi_change_pct"] <= -5:
        trigger_bits.append(f"{abs(inputs['ndvi_change_pct']):.0f}% vegetation loss (NDVI)")
    if inputs.get("suspected_clear_cut"):
        trigger_bits.append("a suspected clear-cut pattern")
    if inputs.get("new_road_detected"):
        trigger_bits.append("a new linear feature consistent with an unauthorized road")
    if inputs.get("sar_change_detected"):
        trigger_bits.append("a SAR backscatter change")
    if inputs.get("storm_event"):
        trigger_bits.append("storm-damage indicators")
    if inputs.get("fire_event"):
        trigger_bits.append("thermal/burn signatures")
    if inputs.get("contractor_activity_outside_boundary"):
        trigger_bits.append("contractor GPS activity outside the assigned boundary")
    if inputs.get("machinery_detected"):
        trigger_bits.append("unexpected machinery presence")
    trigger_txt = " and ".join(trigger_bits) if trigger_bits else "an elevated monitoring score"

    tier = tier_decision["tier"]
    if tier == TIER_3A_OPTICAL_HIGHRES:
        need = "High-resolution optical verification is required."
    elif tier == TIER_3B_SAR_HIGHRES:
        need = "Optical confirmation is not currently possible, so all-weather SAR verification is required."
    elif tier == TIER_2_FREQUENT:
        need = "More frequent monitoring is warranted while this sector is watched."
    else:
        need = "No commercial imagery is warranted at this time."

    return (
        f"{provider_label} requested because Sentinel-2/1 detected {trigger_txt} over "
        f"{area_txt} in sector {sector}, Satellite Risk Score {score} ({band}). {need}"
    )


def check_archive_reuse(sector: str, tier: str, provider: str):
    """Return a recent-enough existing observation to reuse instead of
    ordering new imagery, or None if nothing usable is on file."""
    max_age = ARCHIVE_REUSE_MAX_AGE_DAYS.get(tier)
    if max_age is None:
        return None
    obs = database.get_latest_satellite_observation(sector, provider=provider)
    if not obs or not obs.get("created_at"):
        return None
    try:
        created = datetime.strptime(obs["created_at"].replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    age_days = (datetime.utcnow() - created).days
    return obs if age_days <= max_age else None


def find_combinable_request(sector_center, provider: str):
    """Look for an already-PENDING request (any sector) for the same provider
    whose sector center is within AOI_COMBINE_RADIUS_KM, to combine into one
    AOI instead of two separate commercial requests. Requires sector_center
    (lat, lon) for the sector being evaluated; sector centers for pending
    requests are looked up from the sectors table."""
    if not sector_center:
        return None
    pending = database.get_satellite_requests(approval_status="PENDING", limit=50)
    for req in pending:
        if req["provider"] != provider:
            continue
        other = database.get_sector_geo(req["sector"])
        if not other or other.get("center_lat") is None:
            continue
        dist = _haversine_km(sector_center, (other["center_lat"], other["center_lon"]))
        if dist <= AOI_COMBINE_RADIUS_KM:
            return req
    return None


def decide_and_request(sector_name: str, signals: dict = None, sector_center=None,
                        planetscope_configured=False, source="LIVE") -> dict:
    """
    Full orchestration for one sector: compute the satellite monitoring score,
    persist it (+ a timeline event), decide the tier, and — only for
    MEDIUM+/HIGH/CRITICAL commercial tiers — apply cost control (archive
    reuse check, AOI combination, cost estimate, justification string) and
    persist a satellite_requests row. Returns everything computed so a caller
    (API endpoint, demo seed, event trigger) can act on it without re-querying.

    NORMAL/WATCH sectors are cheap to call repeatedly — no commercial write
    path is even entered.
    """
    signals = signals or {}
    score_result = compute_satellite_monitoring_score(sector_name, signals)

    tier_decision = decide_tier(
        score_result,
        cloud_cover_pct=signals.get("cloud_cover_pct"),
        night=bool(signals.get("night")),
        urgent_all_weather=bool(signals.get("urgent_all_weather")),
        planetscope_configured=planetscope_configured,
    )

    database.add_satellite_score(
        sector_name, score_result["score"], score_result["band"],
        tier_recommended=tier_decision["tier"], inputs=score_result["inputs"],
    )
    database.add_satellite_timeline_event(
        sector_name, "SCORE_UPDATE",
        label=f"Satellite Risk Score {score_result['score']} ({score_result['band']})",
        detail=tier_decision["reason"],
    )

    result = {"score_result": score_result, "tier_decision": tier_decision, "request": None, "reused_archive": None}

    if not tier_decision.get("commercial"):
        return result

    provider = tier_decision["provider"]
    tier = tier_decision["tier"]

    reused = check_archive_reuse(sector_name, tier, provider)
    if reused:
        result["reused_archive"] = reused
        database.add_satellite_timeline_event(
            sector_name, "ARCHIVE_REUSED",
            label=f"Reused existing {provider} observation from {reused.get('created_at')}",
            detail="Sufficient archive imagery already existed — no new commercial request placed.",
            ref_table="satellite_observations", ref_id=reused["id"],
        )
        return result

    aoi_area_ha = signals.get("affected_area_ha") or 1.0
    combined_with = find_combinable_request(sector_center, provider) if tier_decision.get("combinable") else None
    combined_group_id = combined_with["combined_group_id"] if (combined_with and combined_with.get("combined_group_id")) else (
        f"combine-{provider}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}" if combined_with else None
    )

    provider_label = {"skysat": "SkySat", "iceye": "ICEYE", "planetscope": "PlanetScope"}.get(provider, provider)

    cost = estimate_cost(tier, provider, aoi_area_ha)
    justification = build_justification(sector_name, score_result, tier_decision, aoi_area_ha, provider_label)
    resolution = COST_MODEL.get(provider, {}).get("min_resolution_m")

    request_id = database.add_satellite_request(
        sector=sector_name, tier=tier, provider=provider, justification=justification,
        estimated_cost_eur=cost, reason=tier_decision["reason"],
        satellite_risk_score=score_result["score"], requested_resolution_m=resolution,
        aoi_area_ha=aoi_area_ha,
        approval_status="PENDING",
        combined_group_id=combined_group_id,
    )
    result["request"] = database.get_satellite_request(request_id)

    database.add_satellite_timeline_event(
        sector_name, "ESCALATION_REQUESTED",
        label=f"{provider_label} requested ({'immediate' if tier_decision['immediate'] else 'batched' if combined_with else 'standard'})",
        detail=justification, ref_table="satellite_requests", ref_id=request_id,
    )
    if combined_with:
        database.add_satellite_timeline_event(
            sector_name, "AOI_COMBINED",
            label=f"Combined with pending request for sector {combined_with['sector']}",
            detail=f"Geographically close (within {AOI_COMBINE_RADIUS_KM} km) — grouped into one AOI to avoid a duplicate commercial request.",
            ref_table="satellite_requests", ref_id=combined_with["id"],
        )

    return result
