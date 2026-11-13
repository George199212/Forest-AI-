"""F3 forest mask: which pixels of an area (INSIDE + BUFFER) lie in VMD forest-register compartments.

Source: the nationwide VMD index (compartments.sqlite of the ACTIVE release), opened READ-ONLY. Its geometry
column is WGS84 WKB produced at ingest by services/geodata/forestry_io.py (the verified EPSG:10306 converter);
no coordinate conversion happens here. Non-forest pixels are not analysed; their share is stored in
sat_area_masks (metadata). The mask is cached per (area, dataset version) as a .npy file with sha256.
"""
import hashlib
import io
import json
import sqlite3

import numpy as np

from . import config, db as sdb, geometry as geo


class ForestMaskUnavailable(Exception):
    pass


def build(area, cfg=None, path=None):
    """Returns (mask over the full grid, meta). Reads the VMD index read-only."""
    import shapely
    cfg = cfg or config.DEFAULTS
    if path is None:
        path, version = config.forest_db_source()
        if path is None:
            raise ForestMaskUnavailable(version)
    g = area["grid"]
    w, s, e, n = g["bbox"]
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT c.geometry, json_extract(c.properties,'$.zkat') FROM spatial_index s JOIN compartments c "
            "ON c.id=s.id WHERE s.max_lon>? AND s.min_lon<? AND s.max_lat>? AND s.min_lat<?", (w, e, s, n)).fetchall()
        c.close()
    except sqlite3.Error as ex:
        raise ForestMaskUnavailable(f"VMD index not readable: {type(ex).__name__}")
    zk = cfg.get("forest_mask_zkat")
    geoms, zkat_counts = [], {}
    for wkb, z in rows:
        zkat_counts[str(z)] = zkat_counts.get(str(z), 0) + 1
        if zk is None or str(z) in {str(x) for x in zk}:
            geoms.append(shapely.from_wkb(wkb))
    x, y = geo.pixel_centres(g)
    mask = shapely.contains_xy(shapely.union_all(geoms), x, y) if geoms else np.zeros_like(x, dtype=bool)
    return mask.astype(bool), {"n_compartments": len(geoms), "zkat_counts": zkat_counts, "zkat_filter": zk}


def _share(mask, zone):
    n = int(zone.sum())
    return None if n == 0 else round(float((mask & zone).sum()) / n, 4)


def get(conn, area, inside, buffer, cfg=None):
    """Cached mask for the area + active dataset version; writes sat_area_masks on first use."""
    cfg = cfg or config.DEFAULTS
    path, version = config.forest_db_source()
    if path is None:
        raise ForestMaskUnavailable(version)
    zk = cfg.get("forest_mask_zkat")
    key = f"{version}|zkat={json.dumps(zk)}"
    row = conn.execute("SELECT * FROM sat_area_masks WHERE monitored_area_id=? AND kind='VMD_FOREST' AND "
                       "source_version=?", (area["id"], key)).fetchone()
    if row:
        raw = open(row["mask_path"], "rb").read()
        if hashlib.sha256(raw).hexdigest() == row["mask_sha256"]:
            return np.load(io.BytesIO(raw)).astype(bool), dict(row)
    mask, meta = build(area, cfg, path)
    p = config.raster_root() / str(area["id"]) / "masks" / f"vmd_forest_{hashlib.sha256(key.encode()).hexdigest()[:12]}.npy"
    config.secure_dir(p.parent)
    np.save(p, mask)
    config.secure_file(p)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    zone = inside | buffer
    vals = dict(monitored_area_id=area["id"], kind="VMD_FOREST", source_path=str(path), source_version=key,
                created_at_utc=sdb.iso(sdb.utcnow()), mask_path=str(p), mask_sha256=sha,
                n_compartments=meta["n_compartments"], pixels_analysed=int((mask & zone).sum()),
                forest_share_inside=_share(mask, inside), forest_share_buffer=_share(mask, buffer),
                non_forest_share_zone=None if _share(mask, zone) is None else round(1 - _share(mask, zone), 4),
                details_json=sdb.dumps({"zkat_counts": meta["zkat_counts"], "zkat_filter": meta["zkat_filter"]}))
    conn.execute(f"INSERT OR REPLACE INTO sat_area_masks ({', '.join(vals)}) VALUES ({','.join('?' * len(vals))})",
                 tuple(vals.values()))
    conn.commit()
    return mask, vals


# ── Compartment-type classes (METADATA only, 2026-11-13; never used by detection) ─────────────────────────
CLASS_NONE, CLASS_OTHER, CLASS_STAND, CLASS_CLEARCUT = 0, 1, 10, 14


def build_classes(area, path):
    """Per-pixel VMD compartment type: 10 = forest stand (zkat 10), 14 = clear-cut land (zkat 14),
    1 = any other compartment, 0 = no compartment. Overlaps (rare): 14 wins over 10, 10 over other."""
    import shapely
    g = area["grid"]
    w, s, e, n = g["bbox"]
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT c.geometry, json_extract(c.properties,'$.zkat') FROM spatial_index s JOIN compartments c "
            "ON c.id=s.id WHERE s.max_lon>? AND s.min_lon<? AND s.max_lat>? AND s.min_lat<?", (w, e, s, n)).fetchall()
        c.close()
    except sqlite3.Error as ex:
        raise ForestMaskUnavailable(f"VMD index not readable: {type(ex).__name__}")
    groups = {CLASS_OTHER: [], CLASS_STAND: [], CLASS_CLEARCUT: []}
    for wkb, z in rows:
        groups[{"10": CLASS_STAND, "14": CLASS_CLEARCUT}.get(str(z), CLASS_OTHER)].append(shapely.from_wkb(wkb))
    x, y = geo.pixel_centres(g)
    out = np.zeros(x.shape, dtype=np.int8)
    for cls in (CLASS_OTHER, CLASS_STAND, CLASS_CLEARCUT):          # later classes win
        if groups[cls]:
            out[shapely.contains_xy(shapely.union_all(groups[cls]), x, y)] = cls
    return out


def get_classes(area):
    """Cached class raster for the area + ACTIVE dataset version (file only, sha256 in the cache name check)."""
    path, version = config.forest_db_source()
    if path is None:
        raise ForestMaskUnavailable(version)
    key = f"{version}|classes=10,14,other"
    p = config.raster_root() / str(area["id"]) / "masks" / f"vmd_zkat_classes_{hashlib.sha256(key.encode()).hexdigest()[:12]}.npy"
    if p.exists():
        arr = np.load(p)
        if arr.shape == (area["grid"]["height"], area["grid"]["width"]):
            return arr, {"source_version": key, "path": str(p)}
    arr = build_classes(area, path)
    config.secure_dir(p.parent)
    np.save(p, arr)
    config.secure_file(p)
    return arr, {"source_version": key, "path": str(p)}


def split_ha(mask, classes, pixel_area_ha):
    """ha of `mask` per compartment type (METADATA)."""
    f = lambda c: round(int((mask & (classes == c)).sum()) * pixel_area_ha, 4)
    return {"stand_zkat10_ha": f(CLASS_STAND), "clearcut_zkat14_ha": f(CLASS_CLEARCUT),
            "other_compartments_ha": f(CLASS_OTHER), "no_compartment_ha": f(CLASS_NONE)}
