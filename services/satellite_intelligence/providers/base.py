"""
SatelliteProvider interface. Every provider — free baseline (Sentinel/Landsat)
through paid high-res (PlanetScope/SkySat/ICEYE) — implements this so the
decision engine can call any of them identically. See ..models.SatelliteImage
for the shared result shape.
"""

from abc import ABC, abstractmethod

from ..models import SatelliteImage


class SatelliteProvider(ABC):
    name: str = "unknown"
    satellite: str = "unknown"
    tier: str = "1"
    commercial: bool = False

    @abstractmethod
    def is_configured(self) -> bool:
        """True if the credentials/config this provider needs are present.
        Baseline providers (Sentinel-1/2, Landsat) are configured whenever
        Copernicus CDSE credentials are — see sentinel.py, which reads them via
        api.py's existing SENTINEL_CLIENT_ID/SECRET. Commercial adapters check
        their own env var and must return False, never raise, when it's unset.
        """
        raise NotImplementedError

    @abstractmethod
    def fetch(self, bbox: list, date_from: str, date_to: str, **kwargs) -> SatelliteImage:
        """Query the provider for the given AOI/date range. Must NEVER raise —
        on any failure (network, auth, not-configured, no scene) return a
        SatelliteImage with available=False and reason_unavailable set.
        """
        raise NotImplementedError

    def not_configured_result(self, reason: str = "Provider not configured — no credentials in .env") -> SatelliteImage:
        return SatelliteImage(
            provider=self.name, satellite=self.satellite, tier=self.tier,
            available=False, reason_unavailable=reason, source="LIVE",
            cost_eur=(0.0 if self.commercial else None),
        )
