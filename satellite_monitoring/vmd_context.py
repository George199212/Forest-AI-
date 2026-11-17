"""API-side, READ-ONLY context for one change event (Satellite Workspace, owner decisions 2026-11-17).

  compartments(event)  VMD compartments intersecting the event's CURRENT mask (change_geojson): external_id, kvart, nog,
                       zkat, ha_in_mask, p_cirg, p_cirp (AS STORED: NULL stays NULL, 0 / 0.0 stays 0 — the UI renders
                       those as "nav norādīts", never as a year), dataset_version. METADATA only: it never changes
                       classification, confidence or status.
  successor(event)     For a SUPERSEDED event: the current-generation event of the same area whose mask overlaps it most
                       (share of the smaller mask, >= risk_carry_min_overlap), so an old deep link can say
                       "aizstāts ar #60". Nothing is stored; computed on request.

Sources: satellite.db through store.ro() (mode=ro) and the nationwide VMD index (compartments.sqlite of the ACTIVE
release, config.forest_db_source(), opened mode=ro). Areas in LKS-92 / LTM (EPSG:3059) via pyproj only (CLAUDE.md).
Uses shapely + pyproj (present in the forest-api interpreter); store.py stays stdlib-only, so this module is imported
by api_routes, not by store. Results are cached in memory per (event, generation, mask version, dataset version);
nothing is written anywhere.
"""
import json
import sqlite3
from collections import OrderedDict
from functools import lru_cache

from . import config, db as sdb, store

CACHE_SIZE = 256
MIN_HA = 0.0001                     # ignore slivers below 1 m²
_cache = OrderedDict()


class Unavailable(Exception):
    pass


@lru_cache(maxsize=1)
def _to_lks():
    import pyproj
    return pyproj.Transformer.from_crs(4326, 3059, always_xy=True).transform


def _area_ha(geom):
    from shapely.ops import transform
    return transform(_to_lks(), geom).area / 10_000.0


def _mask_geom(change_geojson):
    """Union of the current-mask polygons (INSIDE + BUFFER) as one shapely geometry, or None."""
    import shapely
    from shapely.geometry import shape
    fc = change_geojson or {}
    feats = fc.get("features") if fc.get("type") == "FeatureCollection" else (
        [{"geometry": fc}] if fc.get("type") in ("Polygon", "MultiPolygon") else [])
    geoms = [shape(f["geometry"]) for f in feats or [] if f.get("geometry")]
    geoms = [g if g.is_valid else g.buffer(0) for g in geoms]
    return shapely.union_all(geoms) if geoms else None


def _cache_get(key):
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None


def _cache_put(key, value):
    _cache[key] = value
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)


def _num(v):
    """Pass stored numbers through unchanged; NULL stays None."""
    return v


def compartments(event):
    """-> (items, status). `event` = store.event_detail() dict (needs id, change_geojson, algorithm, updated_at_utc).
    status: {"available": bool, "dataset_version", "reason", "cached"}."""
    path, version = config.forest_db_source()
    if path is None:
        return [], {"available": False, "dataset_version": None, "reason": str(version), "cached": False}
    gen = (event.get("algorithm") or {}).get("generation_id")
    key = ("compartments", event["id"], gen, event.get("updated_at_utc"), version)
    hit = _cache_get(key)
    if hit is not None:
        return hit[0], dict(hit[1], cached=True)
    mask = _mask_geom(event.get("change_geojson"))
    if mask is None or mask.is_empty:
        res = ([], {"available": True, "dataset_version": version, "reason": "event has no current mask", "cached": False})
        _cache_put(key, res)
        return res
    import shapely
    w, s, e, n = mask.bounds
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT c.external_id, c.kvart, c.nog, json_extract(c.properties,'$.zkat'), "
            "json_extract(c.properties,'$.p_cirg'), json_extract(c.properties,'$.p_cirp'), c.geometry "
            "FROM spatial_index s JOIN compartments c ON c.id=s.id "
            "WHERE s.max_lon>? AND s.min_lon<? AND s.max_lat>? AND s.min_lat<?", (w, e, s, n)).fetchall()
        c.close()
    except sqlite3.Error as ex:
        return [], {"available": False, "dataset_version": version, "reason": f"VMD index not readable: {type(ex).__name__}",
                    "cached": False}
    items = []
    for ext, kv, nog, zkat, p_cirg, p_cirp, wkb in rows:
        g = shapely.from_wkb(wkb)
        if not g.is_valid:
            g = g.buffer(0)
        inter = g.intersection(mask)
        if inter.is_empty:
            continue
        ha = _area_ha(inter)
        if ha < MIN_HA:
            continue
        items.append({"external_id": ext, "kvart": kv, "nog": nog, "zkat": None if zkat is None else str(zkat),
                      "ha_in_mask": round(ha, 4), "p_cirg": _num(p_cirg), "p_cirp": _num(p_cirp),
                      "dataset_version": version})
    items.sort(key=lambda x: -x["ha_in_mask"])
    res = (items, {"available": True, "dataset_version": version, "reason": None, "cached": False,
                   "note": "METADATA from the VMD register; it does not change the classification, confidence or status."})
    _cache_put(key, res)
    return res


def successor(event):
    """For a superseded event: {"event_id", "overlap"} of the best current event in the same area, or None."""
    if event.get("current", True):
        return None
    key = ("successor", event["id"], event.get("superseded_by_generation"))
    hit = _cache_get(key)
    if hit is not None:
        return hit
    old = _mask_geom(event.get("change_geojson"))
    best = None
    if old is not None and not old.is_empty:
        conn = store.ro()
        try:
            cand = [dict(r) for r in conn.execute(
                "SELECT id, change_geojson FROM sat_change_events WHERE monitored_area_id=?"
                + sdb.current_only(conn, "sat_change_events"), (event["monitored_area_id"],))]
        finally:
            conn.close()
        a_old = _area_ha(old)
        for c in cand:
            g = _mask_geom(json.loads(c["change_geojson"]) if c["change_geojson"] else None)
            if g is None or g.is_empty:
                continue
            smaller = min(a_old, _area_ha(g))
            if smaller <= 0:
                continue
            ov = _area_ha(old.intersection(g)) / smaller
            if best is None or ov > best["overlap"]:
                best = {"event_id": c["id"], "overlap": round(ov, 3)}
        if best and best["overlap"] < config.DEFAULTS.get("risk_carry_min_overlap", 0.30):
            best = None
    _cache_put(key, best)
    return best
