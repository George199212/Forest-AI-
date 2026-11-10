"""PROCESSED layer: per-pixel indices, validity, per-zone statistics.

No valid pixels -> every statistic is NULL with a reason, never 0."""
import numpy as np

from . import config


def _ratio(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (a - b) / (a + b)
    r[~np.isfinite(r)] = np.nan
    return r


def s2_layers(arr, cfg=None):
    """arr (H,W,6): B04, B08, B11, B12, SCL, dataMask (Process API FLOAT32 reflectance)."""
    cfg = cfg or config.DEFAULTS
    b04, b08, b11, b12, scl, dm = (arr[:, :, i] for i in range(6))
    ndvi = _ratio(b08, b04)
    nbr = _ratio(b08, b12)
    ndmi = _ratio(b08, b11)
    valid = (dm == 1) & np.isin(np.rint(scl).astype(int), cfg["s2_valid_scl"]) \
        & np.isfinite(ndvi) & np.isfinite(nbr) & np.isfinite(ndmi)
    snow = (dm == 1) & (np.rint(scl).astype(int) == 11)
    for a in (ndvi, nbr, ndmi):
        a[~valid] = np.nan
    return {"NDVI": ndvi, "NBR": nbr, "NDMI": ndmi, "valid": valid, "snow": snow}


def s1_layers(arr):
    """arr (H,W,3): VV, VH (linear backscatter), dataMask. dB computed locally."""
    vv, vh, dm = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    valid = (dm == 1) & np.isfinite(vv) & np.isfinite(vh) & (vv > 0) & (vh > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        vv_db = 10.0 * np.log10(vv)
        vh_db = 10.0 * np.log10(vh)
    vh_lin = vh.astype(np.float64).copy()
    for a in (vv_db, vh_db, vh_lin):
        a[~valid] = np.nan
    return {"VV_DB": vv_db, "VH_DB": vh_db, "VH_LIN": vh_lin, "valid": valid}


def zone_stats(values, valid, zone):
    n_total = int(zone.sum())
    sel = valid & zone
    n_valid = int(sel.sum())
    if n_valid == 0:
        return {"mean": None, "median": None, "p10": None, "p90": None,
                "n_valid_pixels": 0, "n_total_pixels": n_total, "null_reason": "NO_VALID_PIXELS"}
    v = values[sel].astype(np.float64)
    return {"mean": float(v.mean()), "median": float(np.median(v)),
            "p10": float(np.percentile(v, 10)), "p90": float(np.percentile(v, 90)),
            "n_valid_pixels": n_valid, "n_total_pixels": n_total, "null_reason": None}


def valid_pct(valid, zone):
    n = int(zone.sum())
    return None if n == 0 else round(100.0 * int((valid & zone).sum()) / n, 3)


def metric_rows(sensor, layers, inside, buffer):
    """Rows for sat_area_metrics: (metric, zone, stats-dict)."""
    rows = []
    names = ["NDVI", "NBR", "NDMI"] if sensor == "S2" else ["VV_DB", "VH_DB"]
    for zone_name, zone in (("INSIDE", inside), ("BUFFER", buffer)):
        for m in names:
            rows.append((m, zone_name, zone_stats(layers[m], layers["valid"], zone)))
        vp = valid_pct(layers["valid"], zone)
        rows.append(("VALID_PCT", zone_name, {"mean": vp, "median": vp, "p10": None, "p90": None,
                                              "n_valid_pixels": int((layers["valid"] & zone).sum()),
                                              "n_total_pixels": int(zone.sum()),
                                              "null_reason": None if vp is not None else "EMPTY_ZONE"}))
        if sensor == "S2":
            sp = valid_pct(layers["snow"], zone)
            rows.append(("SNOW_PCT", zone_name, {"mean": sp, "median": sp, "p10": None, "p90": None,
                                                 "n_valid_pixels": int((layers["snow"] & zone).sum()),
                                                 "n_total_pixels": int(zone.sum()), "null_reason": None}))
    return rows


def null_metric_rows(sensor, reason, n_inside, n_buffer):
    """SKIPPED_CLOUD / ERROR: rows exist (so the timeline shows a gap) but every value is NULL."""
    names = (["NDVI", "NBR", "NDMI", "VALID_PCT", "SNOW_PCT"] if sensor == "S2" else ["VV_DB", "VH_DB", "VALID_PCT"])
    rows = []
    for zone_name, n in (("INSIDE", n_inside), ("BUFFER", n_buffer)):
        for m in names:
            rows.append((m, zone_name, {"mean": None, "median": None, "p10": None, "p90": None,
                                        "n_valid_pixels": None, "n_total_pixels": n, "null_reason": reason}))
    return rows
