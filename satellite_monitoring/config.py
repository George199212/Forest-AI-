"""Configuration. Thresholds are INITIAL values and must be calibrated against
field-verified controls before they are trusted. Every event stores the exact
values it was computed with (thresholds_json), so a later change of these
numbers never silently re-labels history."""
import os
from pathlib import Path

# Worker interpreter: isolated venv built from requirements-satellite.lock (hashed).
# The old /root/forest_ai_satellite_venv (--system-site-packages) is kept until removal is approved.
WORKER_VENV = os.environ.get("SAT_WORKER_VENV", "/root/forest_ai_satellite_venv2")


# ── Paths (env overridable; relative paths resolve against the working dir,
#    the same convention as database.DB_NAME) ─────────────────────────────────
def data_dir() -> Path:
    return Path(os.environ.get("SAT_DATA_DIR", "data"))


def sat_db_path() -> Path:
    return Path(os.environ.get("SAT_DB_PATH", str(data_dir() / "satellite.db")))


def raster_root() -> Path:
    return Path(os.environ.get("SAT_RASTER_DIR", str(data_dir() / "satellite")))


def forest_db_path() -> Path:
    """Main Forest AI DB. Opened READ-ONLY by this package (sqlite mode=ro)."""
    return Path(os.environ.get("FOREST_DB_PATH", os.environ.get("DB_PATH", "data/forest_ai.db")))


def secure_dir(path):
    """Create path (and parents) with mode 700; tighten existing dirs we own up to data_dir()."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    stop = data_dir().resolve()
    cur = p.resolve()
    while True:
        try:
            os.chmod(cur, 0o700)
        except OSError:
            pass
        if cur == stop or cur.parent == cur or stop not in cur.parents:
            break
        cur = cur.parent
    return p


def secure_file(path):
    try:
        os.chmod(path, 0o600)
    except FileNotFoundError:
        pass


DEFAULTS = {
    # Geometry
    "buffer_m": 100.0,
    "pixel_m": 10.0,
    "min_area_ha": 0.1,
    "max_area_ha": 5000.0,
    # Latvia bbox, lon/lat (generous margin around the national border)
    "latvia_bbox": [20.9, 55.6, 28.3, 58.1],

    # Acquisition
    "s2_max_scene_cloud_pct": 80.0,      # above -> SKIPPED_CLOUD, not fetched, NULL metrics
    "s2_valid_scl": [4, 5],              # vegetation, not-vegetated (bare soil)
    # A: SCL cloud shadow (3), cloud medium/high probability (8, 9), thin cirrus (10) are grown by
    # this many pixels (8-neighbourhood, ~10 m each) and the grown ring is invalid too: SCL misses
    # cloud edges/halos, which look like an NDVI/NBR drop.
    "s2_cloud_scl": [3, 8, 9, 10],
    "s2_cloud_dilate_px": 3,
    "min_valid_pct": 60.0,               # below (after dilation) -> never used as baseline or "after"
    "s1_backcoeff": "GAMMA0_ELLIPSOID",
    "s1_dem_instance": "COPERNICUS_30",
    "s1_orthorectify": True,
    "timer_lookback_days": 10,           # TIMER/MANUAL discovery window
    "max_attempts": 3,

    # Quota guards (CDSE free tier: 10,000 PU + 10,000 requests / month)
    "monthly_pu_budget": 2000.0,
    "monthly_request_budget": 6000,
    "guard_stop_fraction": 0.80,
    "max_requests_per_second": 2.0,
    "backoff_base_s": 1.0,
    "backoff_max_retries": 4,

    # Change detection v1 (INITIAL — calibrate)
    "baseline_max_acq": 3,
    "baseline_max_age_days": 90,
    "s2_dnbr_threshold": -0.15,
    "s2_dndvi_threshold": -0.10,
    "s2_dndmi_threshold": -0.10,         # supporting metric only (bare-soil indicator)
    "s1_vh_drop_db": 2.0,
    "s1_filter_size": 3,
    "min_cluster_ha": 0.3,
    "outside_min_ha": 0.3,               # changed ha in BUFFER for POTENTIAL_CHANGE_OUTSIDE_BOUNDARY
    "high_confidence_max_gap_days": 24,  # S1 and S2 both within this -> HIGH
    "ongoing_overlap_fraction": 0.30,
    "ongoing_max_gap_days": 60,

    # B: an optical (S2) change is a PENDING_CONFIRMATION candidate, not an event. The next usable
    # S2 acquisition (same baseline, candidate pixels only) decides: CONFIRMED -> event, else TRANSIENT.
    "candidate_min_comparable_fraction": 0.60,   # share of candidate pixels valid in the next image
    "candidate_persist_fraction": 0.50,          # share of those still changed -> CONFIRMED

    # G: image-level uniform drop (haze/thin cloud/illumination). If >= this share of the comparable
    # pixels (INSIDE+BUFFER) pass the S2 change rule AND the spatial std of dNDVI is low, the image is
    # UNIFORM_DROP_ATMOSPHERIC (classified POSSIBLE_SEASONAL_OR_ENVIRONMENTAL) and, per F, never
    # used as baseline or "after". Known limit: a sector felled almost completely, buffer included,
    # would also look uniform.
    "uniform_drop_min_fraction": 0.60,
    "uniform_drop_max_std_dndvi": 0.10,

    # Classification
    "seasonal_months": [10, 11, 12, 1, 2, 3, 4],   # Oct–Apr (leaf fall/leaf-off, frost, snow, spring thaw)
    "snow_max_pct": 10.0,                # S2: SCL=11 share of the INSIDE zone

    # Evidence quality (separate from detection confidence)
    "eq_good_valid_pct": 80.0, "eq_good_min_baseline": 2, "eq_good_max_gap_days": 30,
    "eq_limited_valid_pct": 60.0, "eq_limited_min_baseline": 1, "eq_limited_max_gap_days": 60,

    # Stage 2 (recorded now so the report shows the full config)
    "auto_risk_min_confidence": "MEDIUM",
    "schedule": "daily 07:30 Europe/Riga (timer prepared in Stage 2, not installed)",
}

# Expected acquisitions per 30 days, used ONLY by the offline --dry-run estimate
# (no Catalog call). Latvia ~57N: Sentinel-2B/2C, 5-day combined revisit plus
# orbit overlap at this latitude; Sentinel-1A/1C IW, several relative orbits
# (ascending + descending). These are planning ESTIMATES, replaced by real
# counts once --dry-run --discover has run.
EXPECTED_PER_30D = {"S2": 15, "S1": 12}

FREE_QUOTA = {"pu": 10000.0, "requests": 10000}


def get(name):
    return DEFAULTS[name]


def thresholds_snapshot():
    keys = ["s2_dnbr_threshold", "s2_dndvi_threshold", "s2_dndmi_threshold", "s1_vh_drop_db",
            "s1_filter_size", "min_cluster_ha", "outside_min_ha", "baseline_max_acq",
            "baseline_max_age_days", "min_valid_pct", "s2_valid_scl", "high_confidence_max_gap_days",
            "ongoing_overlap_fraction", "ongoing_max_gap_days", "seasonal_months", "snow_max_pct",
            "buffer_m", "pixel_m", "s2_cloud_scl", "s2_cloud_dilate_px", "candidate_min_comparable_fraction",
            "candidate_persist_fraction", "uniform_drop_min_fraction", "uniform_drop_max_std_dndvi"]
    return {k: DEFAULTS[k] for k in keys}
