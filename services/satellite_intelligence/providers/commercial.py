"""
Level 2/3 (commercial) provider adapters: PlanetScope, SkySat, ICEYE.

None of these have live credentials yet. Each checks its own env var and
returns a clear "not configured" SatelliteImage when it's missing — it must
NEVER raise or attempt a network call without credentials, so the decision
engine can treat "not configured" as just another normal outcome to route
around (e.g. MEDIUM risk falls back to "increase Level 1 frequency" when
PlanetScope isn't configured, per decision_engine.py).

When credentials ARE eventually supplied via .env, these still return
available=False (with a distinct reason) rather than pretend to call a real
API — the actual HTTP integration is intentionally not implemented until a
real account exists to test against. That keeps this honest instead of
silently faking commercial data.
"""

import os

from ..models import SatelliteImage, TIER_2_FREQUENT, TIER_3A_OPTICAL_HIGHRES, TIER_3B_SAR_HIGHRES
from .base import SatelliteProvider


class PlanetScopeProvider(SatelliteProvider):
    name = "PlanetScope"
    satellite = "PlanetScope (Dove)"
    tier = TIER_2_FREQUENT
    commercial = True
    _ENV_KEY = "PLANETSCOPE_API_KEY"

    def is_configured(self) -> bool:
        return bool(os.environ.get(self._ENV_KEY))

    def fetch(self, bbox: list, date_from: str, date_to: str, **kwargs) -> SatelliteImage:
        if not self.is_configured():
            return self.not_configured_result(
                f"PlanetScope not configured — set {self._ENV_KEY} in .env to activate"
            )
        return self.not_configured_result(
            "PlanetScope credentials detected but the live API client is not yet implemented"
        )


class SkySatProvider(SatelliteProvider):
    name = "SkySat"
    satellite = "SkySat (~50cm/px)"
    tier = TIER_3A_OPTICAL_HIGHRES
    commercial = True
    _ENV_KEY = "SKYSAT_API_KEY"

    def is_configured(self) -> bool:
        return bool(os.environ.get(self._ENV_KEY))

    def fetch(self, bbox: list, date_from: str, date_to: str, **kwargs) -> SatelliteImage:
        if not self.is_configured():
            return self.not_configured_result(
                f"SkySat not configured — set {self._ENV_KEY} in .env to activate"
            )
        return self.not_configured_result(
            "SkySat credentials detected but the live API client is not yet implemented"
        )


class ICEYEProvider(SatelliteProvider):
    name = "ICEYE"
    satellite = "ICEYE (SAR)"
    tier = TIER_3B_SAR_HIGHRES
    commercial = True
    _ENV_KEY = "ICEYE_API_KEY"

    def is_configured(self) -> bool:
        return bool(os.environ.get(self._ENV_KEY))

    def fetch(self, bbox: list, date_from: str, date_to: str, **kwargs) -> SatelliteImage:
        if not self.is_configured():
            return self.not_configured_result(
                f"ICEYE not configured — set {self._ENV_KEY} in .env to activate"
            )
        return self.not_configured_result(
            "ICEYE credentials detected but the live API client is not yet implemented"
        )
