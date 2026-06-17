#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pymupdf>=1.24.0",
# ]
# ///
"""
Vector PDF → Landscape Forms Planner (deterministic path)

Extracts real geometry from a vector PDF via PyMuPDF get_drawings() and
converts it to BlueprintJSON — no vision model, no guessing.

Usage:
  uv run vector_to_planner.py "floor-plan.pdf" [options]

Scale options (pick one):
  --scale 0.084        Raw multiplier on PDF points (1pt * scale = meters).
  --known-width 30.0   Real-world width of the drawing in meters (auto-computes scale).

Common drawing-scale → --scale values (for 1 PDF point = 1/72 inch):
  1"=10'  →  0.042     1"=20'  →  0.085     1"=40'  →  0.169
  1"=50'  →  0.212     1"=100' →  0.423

If unsure, omit scale and the shape will be correct but sized in raw points.
Adjust --scale until the planner shows realistic dimensions.
"""

import argparse
import json
import math
import subprocess
import sys
import webbrowser

PLANNER_URL = "https://landscapeforms.planneren.dev/?family=site-planner"

# Stroke width threshold below which a path is treated as a hairline/annotation
# and excluded. PDF points — 0.5pt ≈ 0.18mm.
MIN_STROKE_WIDTH = 0.5

# Snap tolerance: endpoints within this many PDF points are treated as the same
# vertex. Prevents tiny gaps from breaking closed loops.
SNAP_TOLERANCE = 1.0


def pt_key(pt, tolerance=SNAP_TOLERANCE):
    """Round a point to a grid for snapping near-coincident vertices."""
    return (round(pt.x / tolerance), round(pt.y / tolerance))


def extract_geometry(pdf_path: str, page_index: int):
    """
    Return (drawings, page_height) where drawings is the raw get_drawings() list
    and page_height is used for Y-axis flip.
    """
    import fitz

    doc = fitz.open(pdf_path)
    if page_index >= len(doc):
        print(f"Error: PDF has {len(doc)} pages, requested page {page_index}")
        sys.exit(1)

    page = doc[page_index]
    drawings = page.get_drawings()
    page_height = page.rect.height
    print(f"Page size: {page.rect.width:.1f} x {page_height:.1f} pts")
    print(f"Total drawing paths: {len(drawings)}")
    return drawings, page_height


def is_wall_candidate(d) -> bool:
    """
    Keep paths that look like structural lines rather than fill/hatching.
    Heuristics:
    - Must have a stroke color (color is not None).
    - Must have a stroke width >= MIN_STROKE_WIDTH.
    """
    return d.get("color") is not None and (d.get("width") or 0) >= MIN_STROKE_WIDTH


def flip_y(y: float, page_height: float) -> float:
    """PDF Y origin is top-left (down = positive). Flip to bottom-left (up = positive)."""
    return page_height - y


def path_first_point(d):
    """Return the raw start point of a path's first segment, or None."""
    for item in d["items"]:
        if item[0] == "l":
            return item[1]
        if item[0] == "c":
            return item[1]
        if item[0] == "re":
            return item[1].top_left
        if item[0] == "qu":
            return item[1].ul
    return None


def path_last_point(d):
    """Return the raw end point of a path's last segment, or None."""
    for item in reversed(d["items"]):
        if item[0] == "l":
            return item[2]
        if item[0] == "c":
            return item[4]
        if item[0] == "re":
            return item[1].top_left  # rect closes back to start
        if item[0] == "qu":
            return item[1].ul
    return None


def is_geometrically_closed(d, tolerance=SNAP_TOLERANCE) -> bool:
    """
    True if the path's last point is within tolerance of its first point.
    Catches CAD-exported polylines that are closed in shape but lack closePath=True.
    """
    p0 = path_first_point(d)
    p1 = path_last_point(d)
    if p0 is None or p1 is None:
        return False
    return abs(p0.x - p1.x) <= tolerance and abs(p0.y - p1.y) <= tolerance


def build_blueprint(drawings, scale: float, min_area: float = 0.0,
                    loops_only: bool = False) -> dict:
    """
    Convert filtered drawing paths into BlueprintJSON lines[] and floor[].

    Coordinate strategy:
    - Collect raw PDF points (no Y-flip — avoids sign errors from out-of-bounds paths).
    - After collection, normalize so min=0, then apply scale.
    - Map PDF (x, y) → planner (x, z) with a constant small height y. The planner
      uses three.js convention (Y is UP, ground plane is X-Z). Emitting the 2D
      drawing into X-Y instead stands it up vertically like a wall.
    - A path becomes a floor[] loop if closePath=True OR geometrically closed.

    min_area (m²): if > 0, closed loops whose bounding-box area is below this
    threshold are dropped entirely (both their lines and their floor[] entry).
    This removes noise regions (parking stalls, hatch boxes, small annotation
    boxes). Open paths (walls) are never filtered by area — an axis-aligned wall
    has a near-zero bounding-box height and would be wrongly dropped.

    loops_only: if True, keep only line segments that belong to a floor[] loop
    (reindexing accordingly) and drop all other linework. The planner wants a
    clean closed boundary, not a dump of every interior wall line.
    """
    # First pass: collect raw segments as (x1,y1,x2,y2,width) tuples + floor index lists.
    raw_segs: list[tuple] = []   # (x1, y1, x2, y2, width)
    floor: list[dict] = []

    vertex_map: dict[tuple, tuple] = {}

    def snap_pt(pt):
        key = pt_key(pt)
        if key not in vertex_map:
            vertex_map[key] = (pt.x, pt.y)
        return vertex_map[key]

    def add_seg(p1_raw, p2_raw, width) -> int | None:
        x1, y1 = snap_pt(p1_raw)
        x2, y2 = snap_pt(p2_raw)
        if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
            return None
        idx = len(raw_segs)
        raw_segs.append((x1, y1, x2, y2, width or 1.0))
        return idx

    wall_paths = [d for d in drawings if is_wall_candidate(d)]
    print(f"Wall-candidate paths after filtering: {len(wall_paths)}")

    explicitly_closed = 0
    geometrically_closed = 0
    skipped_small = 0

    for d in wall_paths:
        width = d.get("width")

        # Determine closed-ness up front so the area filter can act before we
        # commit any of this path's segments to lines[].
        closed = d.get("closePath", False)
        is_geom = False
        if not closed:
            closed = is_geometrically_closed(d)
            is_geom = closed

        # Min-area filter — closed loops only (see docstring).
        if closed and min_area > 0:
            r = d.get("rect")
            if r is not None:
                area_m2 = (r.width * scale) * (r.height * scale)
                if area_m2 < min_area:
                    # Count only loops substantial enough to have become a
                    # floor region (>=3 segments); degenerate 1-2 segment
                    # closed paths would have been dropped regardless.
                    prospective = sum(
                        4 if it[0] in ("re", "qu") else 1
                        for it in d["items"]
                        if it[0] in ("l", "c", "re", "qu")
                    )
                    if prospective >= 3:
                        skipped_small += 1
                    continue

        path_indices = []

        for item in d["items"]:
            kind = item[0]
            if kind == "l":
                idx = add_seg(item[1], item[2], width)
                if idx is not None:
                    path_indices.append(idx)
            elif kind == "c":
                idx = add_seg(item[1], item[4], width)
                if idx is not None:
                    path_indices.append(idx)
            elif kind == "re":
                rect = item[1]
                corners = [rect.top_left, rect.top_right, rect.bottom_right, rect.bottom_left]
                for i in range(4):
                    idx = add_seg(corners[i], corners[(i + 1) % 4], width)
                    if idx is not None:
                        path_indices.append(idx)
            elif kind == "qu":
                quad = item[1]
                corners = [quad.ul, quad.ur, quad.lr, quad.ll]
                for i in range(4):
                    idx = add_seg(corners[i], corners[(i + 1) % 4], width)
                    if idx is not None:
                        path_indices.append(idx)

        if len(path_indices) < 3:
            continue

        if closed:
            if is_geom:
                geometrically_closed += 1
            else:
                explicitly_closed += 1
            floor.append({"loop": path_indices})

    # Optional: keep only segments that belong to a floor loop, reindexing.
    if loops_only:
        used = sorted({i for fl in floor for i in fl["loop"]})
        remap = {old: new for new, old in enumerate(used)}
        raw_segs = [raw_segs[i] for i in used]
        for fl in floor:
            fl["loop"] = [remap[i] for i in fl["loop"]]
        print(f"loops-only: kept {len(raw_segs)} segments belonging to {len(floor)} floor loops")

    # Second pass: normalize coordinates (shift to origin) then apply scale.
    if raw_segs:
        min_x = min(min(s[0], s[2]) for s in raw_segs)
        min_y = min(min(s[1], s[3]) for s in raw_segs)
        max_x = max(max(s[0], s[2]) for s in raw_segs)
        max_y = max(max(s[1], s[3]) for s in raw_segs)
        print(f"Raw coordinate bounds: x=[{min_x:.1f}, {max_x:.1f}]  y=[{min_y:.1f}, {max_y:.1f}] pts")
        print(f"Drawing extent: {(max_x-min_x):.1f} x {(max_y-min_y):.1f} pts")
    else:
        min_x = min_y = 0.0

    # Map PDF (x, y) → planner (x, z); Y is the up-axis, held at a small constant
    # so the floor lies flat in the ground plane (matches the planner's presets).
    GROUND_Y = 0.01
    lines = []
    for (x1, y1, x2, y2, w) in raw_segs:
        lines.append({
            "start": {"x": round((x1 - min_x) * scale, 4), "y": GROUND_Y, "z": round((y1 - min_y) * scale, 4)},
            "end":   {"x": round((x2 - min_x) * scale, 4), "y": GROUND_Y, "z": round((y2 - min_y) * scale, 4)},
            "thickness": round(max(w * scale, 0.05), 4),
        })

    print(f"Lines extracted: {len(lines)}")
    print(f"Floor loops: {len(floor)} ({explicitly_closed} explicit closePath, {geometrically_closed} geometric)")
    if min_area > 0:
        print(f"Dropped {skipped_small} closed loops below --min-area {min_area} m²")
    return {"lines": lines, "floor": floor}


def compute_scale_from_known_width(drawings, known_width_m: float) -> float:
    """
    Auto-compute scale so that the bounding box of all wall paths has the given
    real-world width in meters.
    """
    wall_paths = [d for d in drawings if is_wall_candidate(d)]
    if not wall_paths:
        print("Warning: no wall paths found, cannot auto-compute scale")
        return 1.0

    min_x = min_y = math.inf
    max_x = max_y = -math.inf

    for d in wall_paths:
        r = d.get("rect")
        if r:
            min_x = min(min_x, r.x0)
            max_x = max(max_x, r.x1)
            min_y = min(min_y, r.y0)
            max_y = max(max_y, r.y1)

    width_pts = max_x - min_x
    if width_pts <= 0:
        return 1.0

    scale = known_width_m / width_pts
    print(f"Drawing bounding box: {width_pts:.1f} x {max_y - min_y:.1f} pts")
    print(f"Auto-computed scale: {scale:.6f} (1pt = {scale:.4f}m)")
    return scale


def build_inject_script(blueprint: dict) -> str:
    bp_json = json.dumps(blueprint)
    return f"""(function() {{
  var bp = {bp_json};
  function clickBtn(label) {{
    var b = Array.from(document.querySelectorAll('button')).find(function(x) {{
      return x.textContent.trim() === label;
    }});
    if (b) {{ b.click(); return true; }}
    return false;
  }}
  window.planner.blueprint.fromJSON(bp);
  window.planner.blueprint.render();
  setTimeout(function() {{
    // The planner renders the injected blueprint in the top-down "Plan View".
    // (Older builds used a "Next" button; that's gone.)
    if (!clickBtn('Plan View')) {{
      console.warn('Could not find "Plan View" button — rendering in current view');
    }}
    setTimeout(function() {{
      window.planner.blueprint.fromJSON(bp);
      window.planner.engine.forceRender();
      console.log('Blueprint loaded: ' + bp.lines.length + ' lines, ' + bp.floor.length + ' floor regions');
    }}, 500);
  }}, 1000);
}})();"""


def copy_to_clipboard(text: str) -> bool:
    try:
        # Windows
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
        return True
    except Exception:
        try:
            # macOS
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        except Exception:
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert a vector PDF floor plan to Landscape Forms Planner (deterministic)"
    )
    parser.add_argument("pdf_path", help="Path to the PDF floor plan")
    parser.add_argument("--page", type=int, default=0, help="Page index (0-based, default: 0)")
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Multiplier: PDF points → meters (default: 1.0, raw points)",
    )
    parser.add_argument(
        "--known-width",
        type=float,
        default=None,
        metavar="METERS",
        help="Real-world width of the drawing in meters (auto-computes --scale)",
    )
    parser.add_argument(
        "--min-area",
        type=float,
        default=0.0,
        metavar="SQMETERS",
        help="Drop closed loops with bounding-box area below this (m²). "
        "Removes noise regions (parking stalls, hatch boxes). Default: 0 (off).",
    )
    parser.add_argument(
        "--loops-only",
        action="store_true",
        help="Inject only closed-loop regions (drop all non-loop linework). "
        "The planner wants a clean site boundary, not every interior wall line.",
    )
    parser.add_argument("--output", help="Save BlueprintJSON to this file")
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't open the planner URL"
    )
    args = parser.parse_args()

    import os
    if not os.path.exists(args.pdf_path):
        print(f"Error: File not found: {args.pdf_path}")
        sys.exit(1)

    drawings, page_height = extract_geometry(args.pdf_path, args.page)

    scale = args.scale
    if args.known_width is not None:
        scale = compute_scale_from_known_width(drawings, args.known_width)
    elif args.scale == 1.0:
        print(
            "\nNote: using raw PDF points (scale=1.0). Coordinates will be in points, not meters.\n"
            "Pass --scale or --known-width to get real-world meters.\n"
            "Common values: 1\"=20' -> --scale 0.085   1\"=10' -> --scale 0.042\n"
        )

    blueprint = build_blueprint(drawings, scale, min_area=args.min_area,
                                loops_only=args.loops_only)

    if args.output:
        import json as _json
        with open(args.output, "w") as f:
            _json.dump(blueprint, f, indent=2)
        print(f"Saved BlueprintJSON to {args.output}")

    inject_script = build_inject_script(blueprint)
    copied = copy_to_clipboard(inject_script)

    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print(f"1. Open: {PLANNER_URL}")
    if copied:
        print("2. Inject script copied to clipboard.")
    else:
        print("2. Copy the script printed below.")
    print("3. Open DevTools (F12 -> Console).")
    print("4. Paste and press Enter.")
    print("=" * 60)

    if not copied:
        print("\n--- PASTE THIS IN THE BROWSER CONSOLE ---")
        print(inject_script)
        print("--- END OF SCRIPT ---\n")

    if not args.no_browser:
        webbrowser.open(PLANNER_URL)


if __name__ == "__main__":
    main()
