"""Change detection v1 — pure functions on aligned per-area grids.

INTERPRETATION rules (all thresholds INITIAL, from config, stored per event):

S2  baseline = per-pixel median of up to 3 previous VALID acquisitions (VALID_PCT
    INSIDE >= min_valid_pct) within 90 days. Changed if dNBR <= -0.15 AND
    dNDVI <= -0.10. dNDMI is recorded as a supporting bare-soil indicator only.
S1  only the same orbit_direction AND relative_orbit is compared (unknown relative
    orbit -> never compared). 3x3 mean filter on linear VH, then dB. Baseline =
    median of up to 3 earlier same-geometry acquisitions. Changed if VH drops
    >= 2.0 dB. A radar drop becomes an event only if it PERSISTS: the previous
    same-geometry acquisition shows the drop on the same pixels against the same
    baseline. A single drop is stored as an observation (sat_detections) only.
Clusters 8-connected (scipy.ndimage.label, 3x3 structure). Event if the largest
    cluster >= 0.3 ha.
Distances max_distance_outside_boundary_m = largest distance from a changed BUFFER
    pixel centre to the nearest INSIDE pixel centre (pixel-distance approximation,
    accuracy about +-1 pixel / 10 m).

Confidence (DETECTION, about the signal):   S1 only LOW · S2 only MEDIUM ·
    S1 and S2 detections within 24 days HIGH.
Evidence quality (DATA, about the inputs):  GOOD / LIMITED / POOR from VALID_PCT
    of the after image, number of baseline acquisitions and before->after gap.
Neither field states a cause.

Classification (first rule that matches):
  1. INSUFFICIENT_EVIDENCE              evidence_quality == POOR
  2. POSSIBLE_SEASONAL_OR_ENVIRONMENTAL after-image month in Nov–Mar, or snow
                                        (S2 SCL=11) > snow_max_pct of INSIDE
  3. POTENTIAL_CHANGE_OUTSIDE_BOUNDARY  changed area in BUFFER >= outside_min_ha
  4. POTENTIAL_FOREST_LOSS              otherwise
"""
import numpy as np

from . import config

CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
EQ_ORDER = {"POOR": 0, "LIMITED": 1, "GOOD": 2}


def nanmedian_stack(arrays):
    st = np.stack(arrays, axis=0)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmedian(st, axis=0)


def s2_change(after, baselines, zone, cfg=None):
    """after/baselines: dicts with NDVI, NBR, NDMI (NaN where invalid).
    Returns (changed_mask, comparable_mask, d) — d holds the per-pixel deltas."""
    cfg = cfg or config.DEFAULTS
    b_ndvi = nanmedian_stack([b["NDVI"] for b in baselines])
    b_nbr = nanmedian_stack([b["NBR"] for b in baselines])
    b_ndmi = nanmedian_stack([b["NDMI"] for b in baselines])
    d_ndvi, d_nbr, d_ndmi = after["NDVI"] - b_ndvi, after["NBR"] - b_nbr, after["NDMI"] - b_ndmi
    comparable = np.isfinite(d_ndvi) & np.isfinite(d_nbr) & zone
    with np.errstate(invalid="ignore"):
        changed = comparable & (d_nbr <= cfg["s2_dnbr_threshold"]) & (d_ndvi <= cfg["s2_dndvi_threshold"])
        bare = comparable & (d_ndmi <= cfg["s2_dndmi_threshold"])
    return changed, comparable, {"dNDVI": d_ndvi, "dNBR": d_nbr, "dNDMI": d_ndmi, "ndmi_drop": bare}


def mean_filter_db(vh_lin, size=3):
    """NaN-aware size x size mean of linear VH, returned in dB (NaN where no valid neighbour)."""
    from scipy import ndimage
    valid = np.isfinite(vh_lin)
    v = np.where(valid, vh_lin, 0.0)
    s = ndimage.uniform_filter(v, size=size, mode="constant")
    c = ndimage.uniform_filter(valid.astype(np.float64), size=size, mode="constant")
    with np.errstate(divide="ignore", invalid="ignore"):
        m = s / c
        db = 10.0 * np.log10(m)
    db[~valid] = np.nan        # only pixels valid themselves are judged
    return db


def s1_drop(after_vh_lin, baseline_vh_lins, zone, cfg=None):
    cfg = cfg or config.DEFAULTS
    size = cfg["s1_filter_size"]
    a = mean_filter_db(after_vh_lin, size)
    base = nanmedian_stack([mean_filter_db(b, size) for b in baseline_vh_lins])
    drop = base - a
    comparable = np.isfinite(drop) & zone
    with np.errstate(invalid="ignore"):
        changed = comparable & (drop >= cfg["s1_vh_drop_db"])
    return changed, comparable, {"VH_drop_db": drop}


def same_geometry(a, b):
    """S1 comparability: identical orbit direction AND known, identical relative orbit."""
    return (a.get("orbit_direction") is not None and a.get("orbit_direction") == b.get("orbit_direction")
            and a.get("relative_orbit") is not None and a.get("relative_orbit") == b.get("relative_orbit"))


def clusters(mask, pixel_area_ha):
    from scipy import ndimage
    labels, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return labels, np.zeros(0, dtype=int)
    sizes = np.bincount(labels.ravel())[1:]
    return labels, sizes


def event_stats(changed, inside, buffer, dist_to_inside_m, grid, area_ha):
    pa = grid["pixel_area_ha"]
    labels, sizes = clusters(changed, pa)
    n = int(changed.sum())
    ins = int((changed & inside).sum())
    buf = int((changed & buffer).sum())
    outside = changed & buffer
    return {
        "n_changed_pixels": n,
        "changed_area_ha": round(n * pa, 4),
        "changed_area_ha_inside": round(ins * pa, 4),
        "changed_area_ha_buffer": round(buf * pa, 4),
        "pct_of_area_affected": round(100.0 * ins * pa / area_ha, 3) if area_ha else None,
        "largest_cluster_ha": round(float(sizes.max()) * pa, 4) if sizes.size else 0.0,
        "n_clusters": int(sizes.size),
        "max_distance_outside_boundary_m": round(float(dist_to_inside_m[outside].max()), 1) if outside.any() else None,
    }


def keep_large_clusters(changed, grid, min_ha):
    """Pixels of clusters >= min_ha only (small speckle is not part of an event)."""
    labels, sizes = clusters(changed, grid["pixel_area_ha"])
    if sizes.size == 0:
        return np.zeros_like(changed)
    keep_ids = np.where(sizes * grid["pixel_area_ha"] >= min_ha)[0] + 1
    return np.isin(labels, keep_ids)


def confidence(sensor_times):
    """sensor_times: {'S1': [iso...], 'S2': [iso...]} of the detections in the event."""
    from .provider import parse_time
    s1, s2 = sensor_times.get("S1") or [], sensor_times.get("S2") or []
    if s1 and s2:
        gap = min(abs((parse_time(a) - parse_time(b)).days) for a in s1 for b in s2)
        if gap <= config.DEFAULTS["high_confidence_max_gap_days"]:
            return "HIGH"
    if s2:
        return "MEDIUM"
    return "LOW"


def evidence_quality(after_valid_pct, n_baseline, gap_days, cfg=None):
    cfg = cfg or config.DEFAULTS
    if after_valid_pct is None or n_baseline is None or gap_days is None:
        return "POOR"
    if (after_valid_pct >= cfg["eq_good_valid_pct"] and n_baseline >= cfg["eq_good_min_baseline"]
            and gap_days <= cfg["eq_good_max_gap_days"]):
        return "GOOD"
    if (after_valid_pct >= cfg["eq_limited_valid_pct"] and n_baseline >= cfg["eq_limited_min_baseline"]
            and gap_days <= cfg["eq_limited_max_gap_days"]):
        return "LIMITED"
    return "POOR"


def classify(evidence_q, after_month, snow_pct_inside, changed_ha_buffer, cfg=None):
    """Returns (classification, seasonal_caveat or None)."""
    cfg = cfg or config.DEFAULTS
    caveat = None
    if after_month in cfg["seasonal_months"]:
        caveat = ("After-image is from Nov–Mar: leaf-off, frozen/wet ground and snow change "
                  "optical indices and radar backscatter without any felling.")
    elif snow_pct_inside is not None and snow_pct_inside > cfg["snow_max_pct"]:
        caveat = f"Snow on {snow_pct_inside:.0f}% of the area in the after-image."
    if evidence_q == "POOR":
        return "INSUFFICIENT_EVIDENCE", caveat
    if caveat:
        return "POSSIBLE_SEASONAL_OR_ENVIRONMENTAL", caveat
    if changed_ha_buffer is not None and changed_ha_buffer >= cfg["outside_min_ha"]:
        return "POTENTIAL_CHANGE_OUTSIDE_BOUNDARY", None
    return "POTENTIAL_FOREST_LOSS", None


def dilate1(mask):
    """Old event mask grown by one pixel (8-neighbourhood). Ongoing change: once the
    cut is in the baseline, a growing clearing is detected only as its NEW ring,
    which touches the old mask instead of overlapping it."""
    from scipy import ndimage
    return ndimage.binary_dilation(mask, structure=np.ones((3, 3), dtype=bool))


def overlap_fraction(new_mask, old_mask):
    n = int(new_mask.sum())
    return 0.0 if n == 0 else float((new_mask & old_mask).sum()) / n
