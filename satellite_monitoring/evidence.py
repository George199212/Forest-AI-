"""PROCESSED evidence for human review (WORKER only: decodes stored RAW GeoTIFFs).

- mask_series(): per acquisition, the median NDVI/NBR/NDMI (S2) or VH dB (S1) over a mask, from the
  stored RAW raster (sha256 checked). Fewer than min_valid_pct valid mask pixels -> NULL, never 0.
- review_sheet(): before/after tiles (S2 false colour B11/B08/B04, S1 VH dB) with the mask outline
  in yellow. A visual aid, not evidence; the RAW files are the evidence.
No network, no writes to the DB.
"""
import io
import json
from pathlib import Path

import numpy as np

from . import config, metrics as met, raster


def _arr(acq, grid):
    raw = Path(acq["raster_path"]).read_bytes()
    if raster.sha256_bytes(raw) != acq["raster_sha256"]:
        raise ValueError(f"raster sha256 mismatch for acquisition {acq['id']}")
    bands = 6 if acq["sensor"] == "S2" else 3
    return raster.decode_tiff(raw, expected_shape=(grid["height"], grid["width"]), bands=bands)


def mask_series(conn, area, mask, sensor="S2", cfg=None):
    cfg = cfg or config.DEFAULTS
    rows = conn.execute("SELECT * FROM sat_acquisitions WHERE monitored_area_id=? AND sensor=? AND status='OK' "
                        "ORDER BY sensing_time_utc", (area["id"], sensor)).fetchall()
    out, n = [], int(mask.sum())
    for r in rows:
        r = dict(r)
        arr = _arr(r, area["grid"])
        rec = {"acq_id": r["id"], "time": r["sensing_time_utc"], "mask_pixels": n}
        if sensor == "S2":
            L = met.s2_layers(arr, cfg)
            v = L["valid"] & mask
            rec["valid_pct"] = round(100.0 * v.sum() / n, 1) if n else None
            ok = n and rec["valid_pct"] >= cfg["min_valid_pct"]
            for k in ("NDVI", "NBR", "NDMI"):
                rec[k] = round(float(np.nanmedian(L[k][v])), 3) if ok else None
        else:
            L = met.s1_layers(arr)
            v = L["valid"] & mask
            rec["valid_pct"] = round(100.0 * v.sum() / n, 1) if n else None
            with np.errstate(divide="ignore", invalid="ignore"):
                rec["VH_dB"] = round(float(10 * np.log10(np.nanmedian(L["VH_LIN"][v]))), 2) if v.any() else None
            rec["geometry"] = f"{r['orbit_direction']}/{r['relative_orbit']}"
        out.append(rec)
    return out


def _outline(mask):
    m = mask.astype(bool)
    edge = np.zeros_like(m)
    edge[1:, :] |= m[1:, :] != m[:-1, :]
    edge[:, 1:] |= m[:, 1:] != m[:, :-1]
    return edge & m


def review_sheet(conn, area, acq_ids, mask, out_path, scale=4):
    """acq_ids: ordered list of (role, acq_id). Writes a PNG (file mode 600) and returns its path."""
    from PIL import Image, ImageDraw
    tiles = []
    edge = _outline(mask)
    for role, aid in acq_ids:
        acq = dict(conn.execute("SELECT * FROM sat_acquisitions WHERE id=?", (aid,)).fetchone())
        arr = _arr(acq, area["grid"])
        valid = met.s2_layers(arr)["valid"] if acq["sensor"] == "S2" else met.s1_layers(arr)["valid"]
        img = Image.open(io.BytesIO(raster.quicklook_png(acq["sensor"], arr, valid))).convert("RGB")
        a = np.array(img)
        a[edge] = (255, 230, 0)
        img = Image.fromarray(a).resize((a.shape[1] * scale, a.shape[0] * scale), Image.NEAREST)
        canvas = Image.new("RGB", (img.width, img.height + 16), (0, 0, 0))
        canvas.paste(img, (0, 16))
        ImageDraw.Draw(canvas).text((3, 2), f"{role} {acq['sensor']} {acq['sensing_time_utc'][:10]} #{aid}",
                                    fill=(255, 255, 255))
        tiles.append(canvas)
    w = sum(t.width for t in tiles) + 4 * (len(tiles) - 1)
    sheet = Image.new("RGB", (w, max(t.height for t in tiles)), (40, 40, 40))
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width + 4
    out_path = Path(out_path)
    config.secure_dir(out_path.parent)
    sheet.save(out_path, format="PNG", optimize=True)
    config.secure_file(out_path)
    return out_path


def event_review(conn, area, event, out_dir):
    """Series + sheet for one sat_change_events row: last S2 baseline + every after image."""
    """Before tiles: the latest S2 baseline AND the latest S2 image before the first after-image that is
    usable over the event mask itself (>= min_valid_pct of the mask valid), when they differ."""
    mask = np.load(event["change_mask_path"]).astype(bool)
    hist = json.loads(event["after_acq_history_json"])
    s2 = mask_series(conn, area, mask, "S2")
    first_after = min(h["time"] for h in hist)
    after_ids = {h["acq_id"] for h in hist}
    t_of = {r["acq_id"]: r["time"] for r in s2}
    base_s2 = [i for i in json.loads(event["before_acq_ids"]) if i in t_of]
    roles = []
    if base_s2:
        roles.append(("baseline", max(base_s2, key=t_of.get)))
    clear = [r for r in s2 if r["time"] < first_after and r["acq_id"] not in after_ids and r["NDVI"] is not None]
    if clear and (not roles or clear[-1]["acq_id"] != roles[0][1]):
        roles.append(("last clear", clear[-1]["acq_id"]))
    roles += [("after", h["acq_id"]) for h in sorted(hist, key=lambda h: h["time"])]
    sheet = review_sheet(conn, area, roles, mask, Path(out_dir) / f"event_{event['id']}_review.png")
    return {"sheet": str(sheet), "roles": roles, "S2": s2, "S1": mask_series(conn, area, mask, "S1")}
