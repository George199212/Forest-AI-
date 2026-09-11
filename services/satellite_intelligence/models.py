"""
Domain models for the Satellite Intelligence Engine.

Shared by every provider adapter (providers/base.py + its implementations) so the
decision engine and API layer can treat Sentinel-2, Sentinel-1, Landsat, PlanetScope,
SkySat and ICEYE identically — regardless of whether a given query is live, demo, or
"not configured". Nothing here talks to a network or a database; it's pure data shape.
"""

from dataclasses import dataclass, asdict
from typing import Optional


# Tiers, matching the hierarchy in the spec. 3a/3b are alternatives chosen by
# condition (cloud/urgency), not a sequence after 3 — see decision_engine.py.
TIER_1_BASELINE = "1"
TIER_2_FREQUENT = "2"
TIER_3A_OPTICAL_HIGHRES = "3a"
TIER_3B_SAR_HIGHRES = "3b"

TIER_LABELS = {
    TIER_1_BASELINE: "Baseline monitoring",
    TIER_2_FREQUENT: "Frequent monitoring",
    TIER_3A_OPTICAL_HIGHRES: "High-res optical zoom-in",
    TIER_3B_SAR_HIGHRES: "High-res all-weather (SAR)",
}


@dataclass
class SatelliteImage:
    """Result of a provider query — successful or gracefully unavailable.

    `available=False` is the normal "not configured" / "no usable scene" case,
    not an error: every provider must return this instead of raising so the
    decision engine can always reason about what it got back.
    """
    provider: str
    satellite: str
    tier: str
    available: bool = True
    reason_unavailable: Optional[str] = None
    acquisition_date: Optional[str] = None
    resolution_m: Optional[float] = None
    cloud_cover_pct: Optional[float] = None
    bbox: Optional[list] = None            # [min_lon, min_lat, max_lon, max_lat]
    image_id: Optional[str] = None
    image_ref: Optional[str] = None        # local file path or external ref, if persisted
    source: str = "LIVE"                   # LIVE | DEMO
    cost_eur: Optional[float] = None       # None for free/baseline tiers
    risk_score: Optional[float] = None     # satellite_monitoring_score that triggered this acquisition, if any
    ai_analysis_ref: Optional[str] = None  # e.g. "ai_inspector_analyses:123" or "risks:45"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CommercialRequest:
    """A Level 2/3 (paid) imagery request. Always carries a human-readable
    `justification` — per the core principle, Forest AI must be able to explain
    *why* it decided expensive imagery was necessary here. Mirrors the
    satellite_requests table (see database.py) field for field.
    """
    sector: str
    tier: str
    provider: str
    estimated_cost_eur: float
    reason: str                 # short machine reason code, e.g. "HIGH_RISK_VERIFICATION"
    justification: str          # human-readable sentence, shown in UI as-is
    satellite_risk_score: float
    requested_resolution_m: float
    aoi_area_ha: float
    approval_status: str = "PENDING"   # PENDING | APPROVED | REJECTED | FULFILLED
    combined_group_id: Optional[str] = None
    linked_incident_id: Optional[int] = None

    def as_dict(self) -> dict:
        return asdict(self)
