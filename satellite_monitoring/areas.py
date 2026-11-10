"""Monitored areas. Created only by an explicit user action (CLI flag now, API
button in Stage 2/3). One ACTIVE area per (source, source_ref); stopping keeps
the history (active=0, removed_at_utc)."""
import json

from . import config, db as sdb, geometry as geo


class AreaError(ValueError):
    pass


def resolve_sector(name_or_id, forest_conn=None):
    """Sector from forest_ai.db (read-only) -> {source, source_ref, name, geometry}."""
    own = forest_conn is None
    c = forest_conn or sdb.forest_ro()
    try:
        if str(name_or_id).isdigit():
            row = c.execute("SELECT id, name, boundary_json FROM sectors WHERE id=?", (int(name_or_id),)).fetchone()
        else:
            row = c.execute("SELECT id, name, boundary_json FROM sectors WHERE name=?", (str(name_or_id),)).fetchone()
    finally:
        if own:
            c.close()
    if not row:
        raise AreaError(f"sector {name_or_id!r} not found")
    if not row["boundary_json"] or row["boundary_json"] in ("[]", "null"):
        raise AreaError(f"sector {row['name']} has no polygon")
    return {"source": "SECTOR", "source_ref": str(row["id"]), "name": row["name"],
            "geometry": geo.sector_boundary_to_polygon(row["boundary_json"])}


def prepare(geometry, cfg=None):
    """Validate + grid, without writing anything (used by --dry-run too)."""
    cfg = cfg or config.DEFAULTS
    geometry, area_ha = geo.validate(geometry, cfg)
    grid = geo.make_grid(geometry, cfg["buffer_m"], cfg["pixel_m"])
    inside, buffer, _ = geo.masks(geometry, grid, cfg["buffer_m"])
    return {"geometry": geometry, "area_ha": area_ha, "grid": grid,
            "n_inside": int(inside.sum()), "n_buffer": int(buffer.sum())}


def create(conn, source, source_ref, name, geometry, added_by, cfg=None):
    cfg = cfg or config.DEFAULTS
    if source not in ("SECTOR", "LVM_GEO"):
        raise AreaError("source must be SECTOR or LVM_GEO")
    if not source_ref or not name:
        raise AreaError("source_ref and name are required")
    existing = conn.execute("SELECT id FROM sat_monitored_areas WHERE source=? AND source_ref=? AND active=1",
                            (source, str(source_ref))).fetchone()
    if existing:
        return existing["id"], False
    try:
        p = prepare(geometry, cfg)
    except geo.GeometryError as e:
        raise AreaError(str(e))
    cur = conn.execute(
        "INSERT INTO sat_monitored_areas (source, source_ref, name, geometry_geojson, area_ha, buffer_m, grid_json,"
        " added_by, added_at_utc, active) VALUES (?,?,?,?,?,?,?,?,?,1)",
        (source, str(source_ref), name, sdb.dumps(p["geometry"]), p["area_ha"], cfg["buffer_m"],
         sdb.dumps(p["grid"]), added_by, sdb.iso(sdb.utcnow())))
    conn.commit()
    return cur.lastrowid, True


def stop(conn, area_id):
    cur = conn.execute("UPDATE sat_monitored_areas SET active=0, removed_at_utc=? WHERE id=? AND active=1",
                       (sdb.iso(sdb.utcnow()), area_id))
    conn.commit()
    return cur.rowcount == 1


def load(conn, area_id):
    r = conn.execute("SELECT * FROM sat_monitored_areas WHERE id=?", (area_id,)).fetchone()
    if not r:
        return None
    a = dict(r)
    a["geometry"] = json.loads(a["geometry_geojson"])
    a["grid"] = json.loads(a["grid_json"])
    return a


def find(conn, ref):
    """CLI lookup: numeric id, or the name of an area (active first)."""
    if str(ref).isdigit():
        a = load(conn, int(ref))
        if a:
            return a
    r = conn.execute("SELECT id FROM sat_monitored_areas WHERE name=? ORDER BY active DESC, id DESC LIMIT 1",
                     (str(ref),)).fetchone()
    return load(conn, r["id"]) if r else None


def active(conn, ids=None):
    rows = conn.execute("SELECT id FROM sat_monitored_areas WHERE active=1 ORDER BY id").fetchall()
    out = [load(conn, r["id"]) for r in rows]
    if ids:
        ids = {int(i) for i in ids}
        out = [a for a in out if a["id"] in ids]
    return out
