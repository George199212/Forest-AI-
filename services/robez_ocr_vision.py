"""
Robežu Plāns OCR via Claude Vision API.

Replaces the old pytesseract-based analyze_robez_plan_ocr() in bot.py, which
frequently returned 0 coordinate points because Tesseract struggles with
scanned coordinate tables (mixed Latvian/numeric text, noise, skew).

Claude Vision reads the image directly and returns structured JSON, which is
far more robust for this kind of document.

Public function:
    analyze_robez_plan_ocr_vision(image_path: str) -> dict

Returns the SAME shape as the old function, so bot.py / api.py call sites
don't need to change their downstream handling:
{
    "plan_title": str,
    "coordinate_system": str,
    "total_area_ha": float,
    "raw_points": [ {"name": str, "x": float, "y": float, "lat": float, "lon": float}, ... ],
    "proposed_sectors": [ {"suggested_name": str, "description": str, "area_ha": float, "boundary": [[lat,lon], ...]}, ... ],
    "notes": str,
    "ocr_text_preview": str,
}

--------------------------------------------------------------------------
2026-07-09 patch: multi-sector detection
--------------------------------------------------------------------------
Root cause of "only 1 sector found" bug: the prompt only ever asked the model
to trace ONE outer boundary polygon and read ONE total area number from the
land-use table. Plans that visually contain additional smaller enclosed
shapes (sub-plots, restricted zones, building footprints — often drawn with
their own area label like "0.04") were being silently ignored, and
sector_hints stayed empty because nothing asked the model to look for them.

Fix:
- Prompt now asks for every distinct closed shape on the page ("sub_shapes"),
  not just the main outer boundary, and for the FULL land-use table
  ("land_use_rows"), not just the total.
- When the geometric fallback path is used (no coordinate table on the
  plan), we solve meters-per-pixel ONCE from the main boundary + declared
  total area (most reliable, since it's the largest shape), then reuse that
  same scale + reference point to reconstruct every sub_shape's real-world
  coordinates. This avoids solving scale from tiny, error-prone sub-areas.
- Each reconstructed sub_shape becomes its own proposed_sector, named from
  the matching land_use_rows label when the counts line up 1:1 in table
  order, otherwise "Sub-area N".
"""

import os
import json
import base64
import re

import anthropic

# Reuse the exact same approximate LKS-92 -> WGS84 conversion used elsewhere
# in the project (bot.py / database.py), so results stay consistent.
def lks92_to_wgs84(x: float, y: float):
    """Approximate LKS-92 (EPSG:3059) to WGS84 conversion for Latvia.
    X = northing (up), Y = easting (right)
    Accurate to ~100m — good enough for sector planning."""
    lat = (x - 310000) / 111320 + 56.5
    lon = (y - 300000) / 74500 + 24.0
    return round(lat, 6), round(lon, 6)


def calc_centroid(points):
    """points: list of [lat, lon]"""
    if not points:
        return 0.0, 0.0
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    return round(lat, 6), round(lon, 6)


def calc_area_ha(points):
    """Shoelace formula on [lat, lon] pairs, converted to hectares.
    Approximate — good enough for sector planning at this latitude."""
    if len(points) < 3:
        return 0.0
    # rough meters-per-degree at Latvia's latitude
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 74500.0
    xs = [p[1] * m_per_deg_lon for p in points]
    ys = [p[0] * m_per_deg_lat for p in points]
    area_m2 = 0.0
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        area_m2 += xs[i] * ys[j] - xs[j] * ys[i]
    area_m2 = abs(area_m2) / 2.0
    return round(area_m2 / 10000.0, 2)


def _polygon_pixel_area(pixel_points):
    """Shoelace formula in pixel space. pixel_points: list of (px, py)."""
    n = len(pixel_points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = pixel_points[i]
        x2, y2 = pixel_points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _clean_vertex_list(vertices_pixels):
    """Defensively filter out any malformed vertex entries missing pixel coords."""
    clean_vertices = []
    for v in vertices_pixels or []:
        if not isinstance(v, dict):
            continue
        px = v.get("pixel_x")
        py = v.get("pixel_y")
        if px is None or py is None:
            continue
        try:
            px = float(px)
            py = float(py)
        except (TypeError, ValueError):
            continue
        clean_vertices.append({"name": v.get("name", ""), "pixel_x": px, "pixel_y": py})
    return clean_vertices


def _solve_scale_from_reference(reference_point: dict, vertices_pixels: list, total_area_ha):
    """
    Solve meters-per-pixel using ONE known reference point (pixel + real
    LKS-92 coords), the pixel positions of the main boundary vertices, and
    the total declared area (hectares) as a scale-solving anchor.

    Returns (ref_real_x, ref_real_y, ref_px, ref_py, meters_per_pixel) or
    None if reconstruction isn't possible.
    """
    if not reference_point or reference_point.get("real_x") is None or reference_point.get("real_y") is None:
        return None

    try:
        ref_real_x = float(reference_point["real_x"])
        ref_real_y = float(reference_point["real_y"])
    except (TypeError, ValueError):
        return None

    # Sanity check: LKS-92 (EPSG:3059) coordinates for Latvia fall roughly in
    # 200000-800000 for both X and Y. If the model misread or merged digits
    # from two different reference crosses on the page (this happens on
    # plans with more than one "x=... y=..." label), the result can be a
    # garbled number far outside this range. Rather than blocking the whole
    # reconstruction (which left the person with nothing to review at all),
    # flag it as low-confidence and still attempt it — sectors are created
    # in "Draft — needs review" status specifically so a human can catch and
    # fix exactly this kind of thing.
    low_confidence = not (200000 < ref_real_x < 800000 and 200000 < ref_real_y < 800000)

    ref_px = reference_point.get("pixel_x")
    ref_py = reference_point.get("pixel_y")
    if ref_px is None or ref_py is None:
        return None
    try:
        ref_px = float(ref_px)
        ref_py = float(ref_py)
    except (TypeError, ValueError):
        return None

    if not total_area_ha or total_area_ha <= 0:
        return None

    clean_vertices = _clean_vertex_list(vertices_pixels)
    if len(clean_vertices) < 3:
        return None

    pixel_coords = [(v["pixel_x"], v["pixel_y"]) for v in clean_vertices]
    pixel_area = _polygon_pixel_area(pixel_coords)
    if pixel_area <= 0:
        return None

    total_area_m2 = total_area_ha * 10000.0
    # meters per pixel, solved from area ratio (scale-independent of DPI/photo distance)
    meters_per_pixel = (total_area_m2 / pixel_area) ** 0.5

    return ref_real_x, ref_real_y, ref_px, ref_py, meters_per_pixel, low_confidence


def _reconstruct_with_scale(vertices_pixels, ref_real_x, ref_real_y, ref_px, ref_py, meters_per_pixel):
    """Apply an already-solved scale + reference point to any set of pixel
    vertices (main boundary OR a sub-shape) to get real-world coordinates."""
    clean_vertices = _clean_vertex_list(vertices_pixels)
    if len(clean_vertices) < 3:
        return []

    real_points = []
    for v in clean_vertices:
        dx_px = v["pixel_x"] - ref_px
        dy_px = v["pixel_y"] - ref_py
        # image Y grows downward; LKS-92 northing (X) grows upward/north
        dx_m = dx_px * meters_per_pixel          # east-west offset (easting)
        dy_m = -dy_px * meters_per_pixel          # north-south offset (northing), flipped
        real_x = ref_real_x + dy_m   # northing
        real_y = ref_real_y + dx_m   # easting
        lat, lon = lks92_to_wgs84(real_x, real_y)
        real_points.append({
            "name": str(v.get("name", "")),
            "x": round(real_x, 2),
            "y": round(real_y, 2),
            "lat": lat,
            "lon": lon,
            "pixel_x": v["pixel_x"],
            "pixel_y": v["pixel_y"],
        })
    return real_points


def _geometric_reconstruction(reference_point: dict, vertices_pixels: list, total_area_ha):
    """
    Reconstruct real-world LKS-92 coordinates for every vertex of the MAIN
    boundary using one known reference point + declared total area to solve
    scale. Returns list of {"name","x","y","lat","lon"} or [] if
    reconstruction isn't possible.
    """
    solved = _solve_scale_from_reference(reference_point, vertices_pixels, total_area_ha)
    if solved is None:
        return []
    ref_real_x, ref_real_y, ref_px, ref_py, meters_per_pixel, _low_confidence = solved
    return _reconstruct_with_scale(vertices_pixels, ref_real_x, ref_real_y, ref_px, ref_py, meters_per_pixel)


_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


PROMPT = (
    "You are reading a scanned Latvian forestry/land boundary plan "
    "(\"Robežu Plāns\" / \"Situācijas plāns\" / \"Zemes robežu plāns\" / "
    "\"Zemes ierīcības projekts\"). "
    "These documents sometimes contain a full coordinate table listing boundary "
    "points in the LKS-92 (EPSG:3059) coordinate system (X = northing, Y = "
    "easting, both typically 200000-800000), and sometimes instead show only ONE "
    "reference coordinate (often marked like \"x=283200\" / \"y=492000\" near a "
    "cross symbol) plus a hand-drawn polygon with numbered vertices and NO "
    "per-point coordinate table. Some plans show MORE THAN ONE such reference "
    "cross on the page (e.g. one per sub-parcel) — if so, transcribe EACH one "
    "as its own separate entry in \"reference_points\" (see schema below); do "
    "not try to guess which one is \"best\" yourself, and never combine or "
    "concatenate digits read from two different reference labels into one "
    "number.\n\n"
    "IMPORTANT — the parcel may be subdivided in TWO different visual ways, "
    "and either (or both) may be present:\n"
    "(A) Additional smaller enclosed shapes drawn within or beside the main "
    "boundary (e.g. a building footprint, a hatched restricted zone, a "
    "fenced-off sub-plot), each with its own closed outline and often its own "
    "area number printed directly next to it (e.g. \"0.04\").\n"
    "(B) An INTERNAL DIVIDING LINE drawn in a different color or line style "
    "than the main outer boundary (e.g. a dashed red line inside a solid "
    "green outer boundary) that splits the SAME parcel into two or more "
    "named project sub-parcels (often labeled \"Nr.1\", \"Nr.2\", etc., each "
    "with its own area, e.g. in a table titled something like \"Projektētās "
    "zemes vienības\" with columns for a kadastra apzīmējums / cadastral "
    "designation and a Platība (ha) area — this table name varies, it is NOT "
    "always \"ZEMES LIETOŠANAS VEIDU EKSPLIKĀCIJA\"). Each such sub-parcel is "
    "a closed region formed partly by segments of the main outer boundary and "
    "partly by the internal dividing line — trace each one as its own closed "
    "vertex loop.\n"
    "Do not merge sub-parcels/sub-shapes into the main boundary — capture "
    "each one separately using the schema below.\n\n"
    "Carefully read the ENTIRE image and figure out which cases apply, then "
    "return ONLY valid JSON (no markdown fences, no commentary, no preamble) "
    "matching exactly this schema:\n\n"
    "{\n"
    '  "plan_title": "<parcel/plan title, property name, or document type found on the document, or empty string>",\n'
    '  "coordinate_system": "LKS-92",\n'
    '  "map_scale_text": "<printed scale ratio if visible, e.g. \'1:500\', else empty string>",\n'
    '  "total_area_ha": <total parcel area in hectares if a land-use or land-unit table with a total is visible, else null>,\n'
    '  "points": [ {"name": "<point label, e.g. \'1\' or \'Atm-1\'>", "x": <northing number>, "y": <easting number>} ],\n'
    '  "reference_points": [ {\n'
    '    "name": "<vertex label this reference coordinate is closest to, or empty string>",\n'
    '    "real_x": <northing number, or null>,\n'
    '    "real_y": <easting number, or null>,\n'
    '    "pixel_x": <approx horizontal pixel position, 0 = left edge>,\n'
    '    "pixel_y": <approx vertical pixel position, 0 = top edge>\n'
    "  } ],\n"
    '  "vertices_pixels": [ {"name": "<vertex label as written, e.g. \'1\', \'7*\', \'52\'>", "pixel_x": <horizontal pixel position>, "pixel_y": <vertical pixel position>} ],\n'
    '  "sub_shapes": [ {\n'
    '    "name": "<label written on/near this shape or sub-parcel, e.g. \'Nr.2\' or a cadastral designation, or empty string>",\n'
    '    "area_label_ha": <area in hectares printed directly on/near this shape, or from its row in a land-unit/sub-parcel table, or null>,\n'
    '    "vertices_pixels": [ {"name": "<vertex label>", "pixel_x": <horizontal pixel position>, "pixel_y": <vertical pixel position>} ]\n'
    "  } ],\n"
    '  "land_use_rows": [ {"label": "<land-use type or sub-parcel name exactly as printed, e.g. \'Mežs\', \'Nr.2 (80520010084)\'>", "area_ha": <number> } ],\n'
    '  "sector_hints": [ {"name": "<sub-sector name if plan visually divides the parcel>", "point_names": ["<point name>", "..."]} ],\n'
    '  "notes": "<anything unclear, low confidence, or ambiguous worth flagging>"\n'
    "}\n\n"
    "Rules:\n"
    "- \"points\" is for when a REAL coordinate table exists: only include entries "
    "where you can read BOTH X and Y with reasonable confidence from an actual "
    "table with distinct per-row labels and distinct numeric values. Some plans "
    "have a decorative background grid of small unlabeled dots/circles spread "
    "across the whole parcel, used only as a visual scale reference — this is "
    "NOT a coordinate table, even if it looks tabular or repetitive. A telltale "
    "sign of misreading such a grid is many rows with identical or near-"
    "identical X/Y values — if you notice that pattern, treat it as NOT a real "
    "table and return an empty list for \"points\" instead (the geometric "
    "vertices_pixels + reference_point path will be used instead). Do not guess "
    "numbers you cannot see.\n"
    "- \"vertices_pixels\" is ONLY for the MAIN outer parcel boundary, for when "
    "there is NO coordinate table but the polygon is drawn with numbered "
    "vertices: estimate the pixel position of EVERY numbered vertex around the "
    "boundary, in the same order they appear going around the polygon. Use the "
    "full image as your pixel coordinate space. If a real table already covers "
    "all points, leave this empty.\n"
    "- \"sub_shapes\": one entry per ADDITIONAL distinct region besides the main "
    "outer boundary — covering BOTH pattern (A) separate small shapes AND "
    "pattern (B) sub-parcels formed by an internal dividing line (see above). "
    "Estimate vertex pixel positions the same way as \"vertices_pixels\", in "
    "the same shared pixel coordinate space as the main boundary. If the plan "
    "only shows a single undivided shape, return an empty list. Do not invent "
    "sub-parcels that aren't actually drawn.\n"
    "- \"reference_points\": list EVERY single \"x=... y=...\" label you see "
    "anywhere on the page (often near a cross/plus symbol) as its own separate "
    "entry — do not try to pick the \"best\" one yourself and do not merge or "
    "average digits from different labels into one number. Transcribe each "
    "one exactly as printed, independently. If there is only one, return a "
    "list with one entry.\n"
    "- \"total_area_ha\": the TOTAL parcel area — from a land classification "
    "table (\"ZEMES LIETOŠANAS VEIDU EKSPLIKĀCIJA\") OR from a sub-parcel/land-"
    "unit table (e.g. \"Projektētās zemes vienības\") if that's what's present, "
    "usually its summary/total row. Used as a fallback to estimate scale when "
    "no coordinate table exists.\n"
    "- \"land_use_rows\": read every row of whichever table actually has a "
    "PER-ROW NUMERIC AREA in hectares — either a land-use classification table "
    "or a sub-parcel/land-unit table. Return every such row, in table order, "
    "excluding the total/summary row.\n"
    "- CRITICAL — do NOT confuse this with a classification-CODE legend table "
    "(e.g. a list of \"aizsargjoslu klasifikācijas kodi\" / protective-zone "
    "codes mapped to legal descriptions). Those tables list codes and text "
    "explanations but have NO area column — never put their entries in "
    "\"land_use_rows\" and never invent an area number for them. If you cannot "
    "find an actual printed numeric area for a row, leave it out entirely — "
    "do not estimate or fabricate one.\n"
    "- If the number of \"land_use_rows\" roughly matches the number of "
    "\"sub_shapes\" you found (+1 for the main boundary), they likely "
    "correspond 1:1 in order — but don't force a match if the visual shapes "
    "don't support it, and don't invent shapes that aren't actually drawn.\n"
    "- If the document does not show clearly divided sectors via sub_shapes, "
    "return an empty list for \"sector_hints\" — do not invent divisions.\n"
    "- Preserve point order as they appear around each polygon boundary, since "
    "order matters for forming the correct shape.\n"
)


def analyze_robez_plan_ocr_vision(image_path: str) -> dict:
    """
    Analyze a Robežu Plāns scan using Claude Vision API.
    Returns the same dict shape as the legacy pytesseract-based function.
    """
    ext = os.path.splitext(image_path)[1].lower()
    media_type = _MEDIA_TYPES.get(ext, "image/jpeg")

    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return {
            "plan_title": "",
            "coordinate_system": "LKS-92 → WGS84",
            "total_area_ha": 0.0,
            "raw_points": [],
            "proposed_sectors": [],
            "notes": f"Could not read image file: {e}",
            "ocr_text_preview": "",
        }

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        )
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
    except Exception as e:
        return {
            "plan_title": "",
            "coordinate_system": "LKS-92 → WGS84",
            "total_area_ha": 0.0,
            "raw_points": [],
            "proposed_sectors": [],
            "notes": f"Claude Vision API call failed: {e}",
            "ocr_text_preview": "",
        }

    # Claude should return raw JSON, but strip markdown fences defensively
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except Exception as e:
        return {
            "plan_title": "",
            "coordinate_system": "LKS-92 → WGS84",
            "total_area_ha": 0.0,
            "raw_points": [],
            "proposed_sectors": [],
            "notes": f"Could not parse model response as JSON: {e}",
            "ocr_text_preview": raw_text[:500],
        }

    plan_title = parsed.get("plan_title", "") or ""
    model_points = parsed.get("points", []) or []
    sector_hints = parsed.get("sector_hints", []) or []
    model_notes = parsed.get("notes", "") or ""
    # Accept the new "reference_points" list, but fall back to the older
    # singular "reference_point" key too in case the model (or a cached
    # prompt) still returns that shape.
    reference_candidates = parsed.get("reference_points")
    if reference_candidates is None:
        single = parsed.get("reference_point")
        reference_candidates = [single] if single else []
    reference_candidates = [r for r in reference_candidates if r]
    vertices_pixels = parsed.get("vertices_pixels") or []
    sub_shapes = parsed.get("sub_shapes") or []
    land_use_rows = parsed.get("land_use_rows") or []
    total_area_ha_hint = parsed.get("total_area_ha")

    # Convert model points -> raw_points (with lat/lon), same shape the rest
    # of the codebase expects.
    raw_points = []
    for p in model_points:
        try:
            x = float(p.get("x"))
            y = float(p.get("y"))
        except (TypeError, ValueError):
            continue
        if not (200000 < x < 800000 and 200000 < y < 800000):
            continue
        lat, lon = lks92_to_wgs84(x, y)
        raw_points.append({
            "name": str(p.get("name", "")),
            "x": x,
            "y": y,
            "lat": lat,
            "lon": lon,
        })

    # Guard against a corrupted or placeholder "coordinate table": some plans
    # have a decorative background grid of unlabeled dots/circles (used only
    # as a visual scale reference across the whole parcel) that the model can
    # mistake for a real per-point coordinate table. The telltale sign is
    # many near-duplicate coordinates, which collapses the shoelace area to
    # ~0 even though a much larger declared area exists elsewhere on the
    # page. Treat that as "no usable table" and fall through to the
    # geometric (pixel + reference + declared area) reconstruction instead.
    if len(raw_points) >= 3:
        table_area_ha = calc_area_ha([[p["lat"], p["lon"]] for p in raw_points])
        if table_area_ha < 0.05 and total_area_ha_hint and total_area_ha_hint > 0.2:
            raw_points = []

    used_geometric_fallback = False
    used_low_confidence_reference = False
    reference_rejected_out_of_range = False
    solved_scale = None  # (ref_real_x, ref_real_y, ref_px, ref_py, meters_per_pixel)
    if len(raw_points) < 3:
        # No usable coordinate table — try geometric reconstruction from
        # pixel-positioned vertices + one reference point + declared area.
        # Some plans show more than one reference cross; the model may
        # misread one of them, so try every candidate in order rather than
        # trusting a single (possibly garbled) reference point, and use the
        # first one that passes the sanity range check and reconstructs a
        # valid polygon. If none pass cleanly, fall back to the first
        # low-confidence candidate that still reconstructs, rather than
        # giving up entirely — the sector is created as "Draft — needs
        # review" specifically so a human can catch a bad reference.
        any_candidate_seen = bool(reference_candidates)
        best_low_confidence_result = None  # (geo_points, solved_scale) fallback
        used_low_confidence_reference = False
        for candidate in reference_candidates:
            solved = _solve_scale_from_reference(candidate, vertices_pixels, total_area_ha_hint)
            if solved is None:
                continue
            *scale_params, is_low_confidence = solved
            geo_points = _reconstruct_with_scale(vertices_pixels, *scale_params)
            if len(geo_points) < 3:
                continue
            if not is_low_confidence:
                raw_points = geo_points
                used_geometric_fallback = True
                solved_scale = scale_params
                break
            elif best_low_confidence_result is None:
                best_low_confidence_result = (geo_points, scale_params)
        if not used_geometric_fallback and best_low_confidence_result is not None:
            raw_points, solved_scale = best_low_confidence_result
            used_geometric_fallback = True
            used_low_confidence_reference = True
        if not used_geometric_fallback and any_candidate_seen:
            reference_rejected_out_of_range = True

    # Reconstruct any additional sub-shapes using the SAME solved scale +
    # reference point as the main boundary (much more reliable than trying
    # to solve scale independently from a tiny sub-area).
    reconstructed_sub_shapes = []  # list of (label, area_label_ha, points)
    if used_geometric_fallback and solved_scale is not None and sub_shapes:
        for shape in sub_shapes:
            if not isinstance(shape, dict):
                continue
            shape_vertices = shape.get("vertices_pixels") or []
            shape_points = _reconstruct_with_scale(shape_vertices, *solved_scale)
            if len(shape_points) >= 3:
                reconstructed_sub_shapes.append({
                    "name": shape.get("name", "") or "",
                    "area_label_ha": shape.get("area_label_ha"),
                    "points": shape_points,
                })

    # Build proposed sectors
    proposed_sectors = []
    total_area_ha = 0.0

    if sector_hints and raw_points:
        # Use model-provided sector divisions if present (explicit point-name
        # groupings — takes priority over sub_shapes when both are present).
        points_by_name = {p["name"]: p for p in raw_points}
        for idx, hint in enumerate(sector_hints, start=1):
            names = hint.get("point_names", []) or []
            sector_points = [points_by_name[n] for n in names if n in points_by_name]
            if len(sector_points) < 3:
                continue
            boundary = [[p["lat"], p["lon"]] for p in sector_points]
            if boundary[0] != boundary[-1]:
                boundary.append(boundary[0])
            area = calc_area_ha([[p["lat"], p["lon"]] for p in sector_points])
            total_area_ha += area
            pixel_boundary = None
            if all("pixel_x" in p and "pixel_y" in p for p in sector_points):
                pixel_boundary = [[p["pixel_x"], p["pixel_y"]] for p in sector_points]
            proposed_sectors.append({
                "suggested_name": hint.get("name") or f"S-{idx:03d}",
                "description": f"Sector from plan ({len(sector_points)} points)",
                "area_ha": area,
                "boundary": boundary,
                "pixel_boundary": pixel_boundary,
            })
    elif len(raw_points) >= 4:
        # No explicit sector divisions found — treat main boundary as the
        # first sector, then append any reconstructed sub-shapes as
        # additional sectors below.
        boundary = [[p["lat"], p["lon"]] for p in raw_points]
        if boundary[0] != boundary[-1]:
            boundary.append(boundary[0])
        area = calc_area_ha([[p["lat"], p["lon"]] for p in raw_points])
        total_area_ha = area
        pixel_boundary = None
        if all("pixel_x" in p and "pixel_y" in p for p in raw_points):
            pixel_boundary = [[p["pixel_x"], p["pixel_y"]] for p in raw_points]
        proposed_sectors.append({
            "suggested_name": "S-001",
            "description": f"Main boundary from plan ({len(raw_points)} points)",
            "area_ha": area,
            "boundary": boundary,
            "pixel_boundary": pixel_boundary,
        })

        # Try to line up land_use_rows labels with sub-shapes in table order
        # (main boundary implicitly consumes the first/total-ish row, so we
        # offer whatever labels are left over, best-effort).
        leftover_labels = [row.get("label", "") for row in land_use_rows if isinstance(row, dict)]

        for i, shape in enumerate(reconstructed_sub_shapes, start=2):
            shape_points = shape["points"]
            boundary = [[p["lat"], p["lon"]] for p in shape_points]
            if boundary[0] != boundary[-1]:
                boundary.append(boundary[0])
            area = calc_area_ha([[p["lat"], p["lon"]] for p in shape_points])
            total_area_ha += area
            pixel_boundary = None
            if all("pixel_x" in p and "pixel_y" in p for p in shape_points):
                pixel_boundary = [[p["pixel_x"], p["pixel_y"]] for p in shape_points]

            label = shape["name"]
            if not label and (i - 2) < len(leftover_labels):
                label = leftover_labels[i - 2]
            suggested_name = f"S-{i:03d}"
            area_note = ""
            if shape["area_label_ha"] is not None:
                area_note = f", labeled {shape['area_label_ha']} ha on plan"

            proposed_sectors.append({
                "suggested_name": suggested_name,
                "description": (
                    f"Sub-area from plan ({len(shape_points)} points)"
                    + (f" — {label}" if label else "")
                    + area_note
                ),
                "area_ha": area,
                "boundary": boundary,
                "pixel_boundary": pixel_boundary,
            })

    if used_geometric_fallback:
        notes = (
            f"No coordinate table found on this plan. Reconstructed {len(raw_points)} "
            f"vertex positions GEOMETRICALLY from pixel positions + one reference "
            f"coordinate + declared total area ({total_area_ha_hint} ha). "
        )
        if used_low_confidence_reference:
            notes += (
                "⚠️⚠️ LOW CONFIDENCE: the reference coordinate used looked implausible "
                "(outside the typical 200000-800000 LKS-92 range for Latvia) — it was "
                "likely misread, or digits from two different reference crosses on the "
                "page got merged. The sector shape/area should still be roughly right, "
                "but its real-world POSITION (map/satellite placement) may be off. "
                "Please verify the location on the map before relying on it. "
            )
        if reconstructed_sub_shapes:
            notes += (
                f"Also detected {len(reconstructed_sub_shapes)} additional sub-shape(s) "
                f"on the plan, reconstructed using the same scale. "
            )
        notes += (
            "⚠️ Accuracy is approximate — depends on scan alignment and how precisely "
            "vertex pixel positions were read. Verify against the source document before "
            "relying on this for legal/financial decisions."
        )
    else:
        notes = f"OCR (Claude Vision) extracted {len(raw_points)} coordinate points from plan. "
        if len(raw_points) == 0:
            notes += "No coordinates found — plan may be unclear, handwritten, or in an unsupported format."
        elif len(raw_points) < 4:
            notes += f"Only {len(raw_points)} points found — need minimum 3-4 for a polygon."
        if reference_rejected_out_of_range:
            notes += (
                " ⚠️ A reference coordinate was detected but rejected as implausible "
                "(outside the 200000-800000 LKS-92 range) — likely misread, or digits "
                "from two different reference crosses got merged. Geometric "
                "reconstruction was skipped rather than risk a skewed result."
            )
    if model_notes:
        notes += f" Model notes: {model_notes}"
    if land_use_rows:
        rows_preview = "; ".join(
            f"{row.get('label', '')}: {row.get('area_ha', '')} ha"
            for row in land_use_rows if isinstance(row, dict)
        )
        notes += f" Land-use table rows: {rows_preview}."

    georef_scale = None
    if used_geometric_fallback and solved_scale is not None:
        ref_real_x, ref_real_y, ref_px, ref_py, meters_per_pixel = solved_scale
        georef_scale = {
            "ref_real_x": ref_real_x,
            "ref_real_y": ref_real_y,
            "ref_px": ref_px,
            "ref_py": ref_py,
            "meters_per_pixel": meters_per_pixel,
        }

    return {
        "plan_title": plan_title[:100],
        "coordinate_system": "LKS-92 → WGS84",
        "total_area_ha": round(total_area_ha, 2),
        "raw_points": raw_points,
        "proposed_sectors": proposed_sectors,
        "notes": notes,
        "ocr_text_preview": raw_text[:500],
        # Lets the dashboard convert NEW manually-drawn sector polygons (on
        # this same plan image) into real LKS-92/WGS84 coordinates later,
        # without needing to re-run OCR. Only present when the geometric
        # fallback path was used (i.e. we actually solved a scale).
        "georef_scale": georef_scale,
    }
