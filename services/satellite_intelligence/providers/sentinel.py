"""
Level 1 (baseline) providers: Sentinel-2, Sentinel-1, Landsat.

These build on — and deliberately do NOT duplicate or modify — api.py's existing
get_sentinel_token() (OAuth against Copernicus Data Space Ecosystem, cached) and
query_sentinel_ndvi() (Sentinel-2 L2A NDVI via the Sentinel Hub process API).
Both are imported lazily (inside methods, not at module load time) to avoid a
circular import: api.py imports the decision engine from this package, so this
package cannot import api.py at module scope.

Sentinel-1 (SAR) and Landsat reuse the same OAuth token and the same process-API
request shape as query_sentinel_ndvi, generalized to other collections. Sentinel-1
matters specifically because it sees through cloud cover that blocks Sentinel-2 —
that's *why* it's a distinct Level-1 source, not a redundant one.
"""

import json as _json
import urllib.request

from ..models import SatelliteImage, TIER_1_BASELINE
from .base import SatelliteProvider


def _get_token():
    from api import get_sentinel_token
    return get_sentinel_token()


def _api_url():
    from api import SENTINEL_API_URL
    return SENTINEL_API_URL


def _process_request(evalscript: str, collection: str, bbox: list, date_from: str,
                      date_to: str, max_cloud_coverage=None, width=512, height=512) -> bytes:
    """Generalized version of api.query_sentinel_ndvi()'s request-building, for
    collections other than sentinel-2-l2a. Same auth, same endpoint, same
    try/except-return-None-on-failure contract — never raises.
    """
    token = _get_token()
    if not token:
        return None

    data_filter = {"timeRange": {"from": date_from + "T00:00:00Z", "to": date_to + "T23:59:59Z"}}
    if max_cloud_coverage is not None:
        data_filter["maxCloudCoverage"] = max_cloud_coverage

    payload = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}
            },
            "data": [{"type": collection, "dataFilter": data_filter}]
        },
        "evalscript": evalscript,
        "output": {
            "width": width, "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}]
        }
    }

    req = urllib.request.Request(_api_url(), data=_json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception:
        return None


class Sentinel2Provider(SatelliteProvider):
    """Optical, 10m, ~5 day revisit. Thin wrapper around the existing
    get_sentinel_token()/query_sentinel_ndvi() — the actual image bytes are
    still served by the existing /api/satellite/image and /ndvi endpoints,
    unchanged. This provider answers "is it usable right now" for the
    decision engine, and can optionally fetch bytes for the observation log.
    """
    name = "Sentinel-2"
    satellite = "Sentinel-2 L2A"
    tier = TIER_1_BASELINE
    commercial = False

    def is_configured(self) -> bool:
        return _get_token() is not None

    def fetch(self, bbox: list, date_from: str, date_to: str, fetch_image=False, **kwargs) -> SatelliteImage:
        if not self.is_configured():
            return self.not_configured_result(
                "Copernicus CDSE token unavailable — check SENTINEL_CLIENT_ID/SENTINEL_CLIENT_SECRET in .env"
            )
        image_bytes = None
        if fetch_image:
            from api import query_sentinel_ndvi
            image_bytes = query_sentinel_ndvi(bbox, date_from, date_to)
            if image_bytes is None:
                return SatelliteImage(
                    provider=self.name, satellite=self.satellite, tier=self.tier,
                    available=False, reason_unavailable="No cloud-free Sentinel-2 scene in the requested range",
                    bbox=bbox, source="LIVE",
                )
        return SatelliteImage(
            provider=self.name, satellite=self.satellite, tier=self.tier,
            available=True, acquisition_date=date_to, resolution_m=10.0,
            bbox=bbox, source="LIVE", cost_eur=None,
            image_id=f"s2:{date_from}:{date_to}" if image_bytes else None,
        )


class Sentinel1Provider(SatelliteProvider):
    """SAR, ~10-20m depending on mode, weather/cloud/night independent.
    Used specifically when cloud cover blocks Sentinel-2 optical — see
    decision_engine.py's 3a-vs-3b choice, which applies the same logic at
    Level 1 already implicit here.
    """
    name = "Sentinel-1"
    satellite = "Sentinel-1 GRD (SAR)"
    tier = TIER_1_BASELINE
    commercial = False

    _EVALSCRIPT = """
//VERSION=3
function setup() {
  return { input: [{ bands: ["VV", "dataMask"] }], output: { bands: 1 } };
}
function evaluatePixel(sample) {
  if (sample.dataMask === 0) return [NaN];
  return [sample.VV];
}
"""

    def is_configured(self) -> bool:
        return _get_token() is not None

    def fetch(self, bbox: list, date_from: str, date_to: str, fetch_image=False, **kwargs) -> SatelliteImage:
        if not self.is_configured():
            return self.not_configured_result(
                "Copernicus CDSE token unavailable — check SENTINEL_CLIENT_ID/SENTINEL_CLIENT_SECRET in .env"
            )
        if fetch_image:
            image_bytes = _process_request(self._EVALSCRIPT, "sentinel-1-grd", bbox, date_from, date_to)
            if image_bytes is None:
                return SatelliteImage(
                    provider=self.name, satellite=self.satellite, tier=self.tier,
                    available=False, reason_unavailable="Sentinel-1 GRD query failed or no scene in range",
                    bbox=bbox, source="LIVE",
                )
        return SatelliteImage(
            provider=self.name, satellite=self.satellite, tier=self.tier,
            available=True, acquisition_date=date_to, resolution_m=10.0,
            cloud_cover_pct=0.0,  # SAR — cloud cover is not a limiting factor
            bbox=bbox, source="LIVE", cost_eur=None,
        )


class LandsatProvider(SatelliteProvider):
    """Optical, 30m, ~16 day revisit. Best-effort live attempt: Copernicus
    Data Space Ecosystem's process API hosts a landsat-ot-l2 collection, but
    availability can vary by account/plan. On any failure this degrades to
    available=False rather than raising — same contract as every other
    provider here.
    """
    name = "Landsat"
    satellite = "Landsat 8/9 OLI-2"
    tier = TIER_1_BASELINE
    commercial = False

    _EVALSCRIPT = """
//VERSION=3
function setup() {
  return { input: [{ bands: ["B04", "B05", "dataMask"] }], output: { bands: 1 } };
}
function evaluatePixel(sample) {
  if (sample.dataMask === 0) return [NaN];
  let ndvi = (sample.B05 - sample.B04) / (sample.B05 + sample.B04);
  return [ndvi];
}
"""

    def is_configured(self) -> bool:
        return _get_token() is not None

    def fetch(self, bbox: list, date_from: str, date_to: str, fetch_image=False, **kwargs) -> SatelliteImage:
        if not self.is_configured():
            return self.not_configured_result(
                "Copernicus CDSE token unavailable — check SENTINEL_CLIENT_ID/SENTINEL_CLIENT_SECRET in .env"
            )
        if fetch_image:
            image_bytes = _process_request(self._EVALSCRIPT, "landsat-ot-l2", bbox, date_from, date_to,
                                            max_cloud_coverage=30)
            if image_bytes is None:
                return SatelliteImage(
                    provider=self.name, satellite=self.satellite, tier=self.tier,
                    available=False,
                    reason_unavailable="Landsat query failed, no scene in range, or collection unavailable on this CDSE plan",
                    bbox=bbox, source="LIVE",
                )
        return SatelliteImage(
            provider=self.name, satellite=self.satellite, tier=self.tier,
            available=True, acquisition_date=date_to, resolution_m=30.0,
            bbox=bbox, source="LIVE", cost_eur=None,
        )
