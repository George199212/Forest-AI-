"""
Satellite Intelligence Engine.

Core principle: Forest AI does not buy expensive satellite imagery everywhere.
AI decides where expensive imagery is actually necessary.

This package is additive to the existing Sentinel Hub integration in api.py
(get_sentinel_token / query_sentinel_ndvi / the /api/satellite/* endpoints),
which stays untouched and keeps serving imagery exactly as it does today. This
package adds a decision layer on top: which tier of satellite is worth using,
per sector, right now — see providers/ for the tier implementations and
decision_engine.py (added in a later stage) for the escalation logic.
"""

from .models import (
    SatelliteImage, CommercialRequest,
    TIER_1_BASELINE, TIER_2_FREQUENT, TIER_3A_OPTICAL_HIGHRES, TIER_3B_SAR_HIGHRES,
    TIER_LABELS,
)
from .risk_score import compute_satellite_monitoring_score
from .decision_engine import decide_tier, decide_and_request

__all__ = [
    "SatelliteImage", "CommercialRequest",
    "TIER_1_BASELINE", "TIER_2_FREQUENT", "TIER_3A_OPTICAL_HIGHRES", "TIER_3B_SAR_HIGHRES",
    "TIER_LABELS",
    "compute_satellite_monitoring_score",
    "decide_tier", "decide_and_request",
]
