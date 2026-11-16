"""Display-only geometry for the UI (Stage 3). API process; shapely is imported lazily (system python has it).

buffer_ring: the area polygon grown by buffer_m minus the polygon, in the SAME local equirectangular scale the
worker uses for its grid (geometry.make_grid / masks: metres per degree at the polygon's mean latitude). The worker
classifies BUFFER pixels on a 10 m raster (+-1 pixel), so this outline is an approximation for display; detection
never uses it. Returns None (overlay hidden) when shapely is unavailable or the geometry cannot be buffered.
"""
import math

M_PER_DEG = 111320.0          # same constant as satellite_monitoring.geometry


def buffer_ring(geometry, buffer_m):
    try:
        from shapely.geometry import mapping, shape
        from shapely.ops import transform
    except ImportError:
        return None
    try:
        g = shape(geometry)
        minx, miny, maxx, maxy = g.bounds
        lat0 = (miny + maxy) / 2.0
        kx = M_PER_DEG * math.cos(math.radians(lat0))
        fwd = lambda x, y, z=None: (x * kx, y * M_PER_DEG)
        inv = lambda x, y, z=None: (x / kx, y / M_PER_DEG)
        local = transform(fwd, g)
        ring = local.buffer(float(buffer_m), 16).difference(local)
        if ring.is_empty:
            return None
        return mapping(transform(inv, ring))
    except Exception:
        return None
