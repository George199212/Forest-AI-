"""Raster I/O for the WORKER only (needs tifffile from /root/forest_ai_satellite_venv).
The API process never imports this module: it serves stored PNG quicklooks."""
import hashlib
import io
import re
from pathlib import Path

import numpy as np

from . import config


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def decode_tiff(raw, expected_shape=None, bands=None):
    """GeoTIFF bytes -> float32 array (H, W, B)."""
    import tifffile
    arr = tifffile.imread(io.BytesIO(raw))
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr[:, :, None]
    if arr.ndim == 3 and bands is not None and arr.shape[0] == bands and arr.shape[2] != bands:
        arr = np.moveaxis(arr, 0, -1)          # planar config -> band-last
    if expected_shape is not None and arr.shape[:2] != tuple(expected_shape):
        raise ValueError(f"raster shape {arr.shape[:2]} != grid {tuple(expected_shape)}")
    if bands is not None and arr.shape[2] != bands:
        raise ValueError(f"raster has {arr.shape[2]} bands, expected {bands}")
    return arr


def safe_name(product_id):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", product_id)[:90]


def raster_paths(area_id, sensor, sensing_time_utc, product_id, root=None):
    root = Path(root or config.raster_root())
    d = root / str(int(area_id)) / sensor
    stem = f"{sensing_time_utc[:10]}_{safe_name(product_id)}"
    return d / f"{stem}.tif", d / f"{stem}.png"


def write_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return sha256_bytes(data)


def _stretch(a, valid):
    out = np.zeros(a.shape, dtype=np.uint8)
    if valid.any():
        lo, hi = np.percentile(a[valid], [2, 98])
        if hi <= lo:
            hi = lo + 1e-6
        out = (np.clip((a - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
    return out


def quicklook_png(sensor, arr, valid):
    """PROCESSED visual only (not evidence). S2: false colour SWIR1/NIR/Red
    (B11, B08, B04) — healthy forest green, clear-cut magenta/brown.
    S1: VH backscatter in dB, grey -25..-5 dB. Invalid pixels: mid grey."""
    from PIL import Image
    if sensor == "S2":
        rgb = np.dstack([_stretch(arr[:, :, 2], valid), _stretch(arr[:, :, 1], valid), _stretch(arr[:, :, 0], valid)])
    else:
        with np.errstate(divide="ignore", invalid="ignore"):
            vh = 10.0 * np.log10(arr[:, :, 1])
        g = (np.clip((np.nan_to_num(vh, nan=-25.0) + 25.0) / 20.0, 0, 1) * 255).astype(np.uint8)
        rgb = np.dstack([g, g, g])
    rgb[~valid] = (128, 128, 128)
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
