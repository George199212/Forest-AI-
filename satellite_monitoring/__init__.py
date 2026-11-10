"""Satellite Monitoring (Sentinel-1 + Sentinel-2) for monitored areas.

Separate from services/satellite_intelligence (on-demand, never persisted) and
from the demo adapters. Everything here is real Copernicus data or NULL with a
reason; nothing is simulated. Automated output is always a *suspected* change.

Layers kept apart on purpose:
  RAW            sat_acquisitions + the GeoTIFF bytes exactly as CDSE returned them (sha256)
  PROCESSED      sat_area_metrics (per-zone statistics), change masks
  INTERPRETATION sat_change_events (classification, confidence, evidence quality)
  HUMAN DECISION sat_review_log / event status REVIEW_* (Stage 2)

The worker (CLI, timer) runs in /root/forest_ai_satellite_venv (tifffile). The
API process never imports raster decoding (satellite_monitoring.raster).
"""
