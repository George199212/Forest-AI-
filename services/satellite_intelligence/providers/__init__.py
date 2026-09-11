from .base import SatelliteProvider
from .sentinel import Sentinel2Provider, Sentinel1Provider, LandsatProvider
from .commercial import PlanetScopeProvider, SkySatProvider, ICEYEProvider

ALL_PROVIDERS = {
    "sentinel2": Sentinel2Provider(),
    "sentinel1": Sentinel1Provider(),
    "landsat": LandsatProvider(),
    "planetscope": PlanetScopeProvider(),
    "skysat": SkySatProvider(),
    "iceye": ICEYEProvider(),
}

__all__ = [
    "SatelliteProvider",
    "Sentinel2Provider", "Sentinel1Provider", "LandsatProvider",
    "PlanetScopeProvider", "SkySatProvider", "ICEYEProvider",
    "ALL_PROVIDERS",
]
