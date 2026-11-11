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
