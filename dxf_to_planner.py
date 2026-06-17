#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "ezdxf>=1.1",
# ]
# ///
"""
DXF → Landscape Forms Planner (deterministic, units-aware)

Preferred input path when the drawing's author can hand us a DXF. Unlike the PDF
route (vector_to_planner.py), a DXF carries:
  - real-world UNITS, so scale is read, not guessed; and
  - the site boundary as a single CLOSED polyline, so there's no stitching.

Usage:
  uv run dxf_to_planner.py "site.dxf"                  # auto: largest closed loop
  uv run dxf_to_planner.py "site.dxf" --layer C-PROP   # only entities on a layer
  uv run dxf_to_planner.py "site.dxf" --all-loops      # every closed polyline
  uv run dxf_to_planner.py "site.dxf" --units feet     # override if DXF is unitless

Outputs the same BlueprintJSON + console-inject script as the PDF tool, reusing
its inject/clipboard/browser plumbing.

STATUS: sketch — structure is complete and should run, but a few branches are
marked NOTE/TODO to verify against a real DXF (entity types present, layer names,
whether Y needs flipping, units header). We can't validate end-to-end until we
have a file.
"""

import argparse
import math
import os
import sys
import webbrowser

# Reuse the planner-facing machinery from the PDF tool. Its `import fitz` is lazy
# (inside functions), so importing these does NOT require pymupdf to be present.
from vector_to_planner import build_inject_script, copy_to_clipboard, PLANNER_URL

# Planner uses three.js convention: Y is UP, the ground plane is X-Z. Keep the
# floor flat by holding Y at a small constant (matches the planner's presets).
GROUND_Y = 0.01

# Snap/close tolerance in meters for treating a polyline as closed.
CLOSE_TOL_M = 0.05

# DXF $INSUNITS header code → meters per drawing unit. Only the common ones; the
# rest warn and fall back to --units / unitless.
INSUNITS_TO_METERS = {
    0: None,            # unitless — must supply --units
    1: 0.0254,          # inches
    2: 0.3048,          # feet
    4: 0.001,           # millimeters
    5: 0.01,            # centimeters
    6: 1.0,             # meters
    10: 0.9144,         # yards
    14: 0.1,            # decimeters
    21: 0.3048006096,   # US survey feet (common on US site/survey plans)
}

# Friendly --units names → meters per unit (for unitless DXFs).
UNIT_NAME_TO_METERS = {
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
    "mm": 0.001, "cm": 0.01, "m": 1.0, "meter": 1.0, "meters": 1.0,
    "yd": 0.9144, "yard": 0.9144,
    "usft": 0.3048006096, "ussurveyfeet": 0.3048006096,
}


def resolve_units(doc, override: str | None) -> tuple[float, str]:
    """Return (meters_per_unit, label). --units override wins; else DXF header."""
    if override:
        key = override.strip().lower()
        if key not in UNIT_NAME_TO_METERS:
            print(f"Error: unknown --units '{override}'. Known: {sorted(UNIT_NAME_TO_METERS)}")
            sys.exit(1)
        return UNIT_NAME_TO_METERS[key], f"{override} (override)"

    code = doc.header.get("$INSUNITS", 0)
    mpu = INSUNITS_TO_METERS.get(code, "unknown")
    if mpu is None:
        print(
            "DXF reports $INSUNITS=0 (unitless). Pass --units (e.g. --units feet) "
            "so coordinates can be converted to meters."
        )
        sys.exit(1)
    if mpu == "unknown":
        print(
            f"DXF $INSUNITS={code} is not in the lookup table. Pass --units explicitly."
        )
        sys.exit(1)
    return mpu, f"$INSUNITS={code}"


def entity_to_points(entity, flatten_tol_units: float) -> list[tuple[float, float]]:
    """
    Flatten any supported DXF entity to a list of (x, y) points in drawing units.

    Uses ezdxf's path module, which tessellates bulges (arc segments in
    LWPOLYLINE), ARC, CIRCLE, ELLIPSE and SPLINE into smooth point runs — this is
    what gives us real curves instead of the faceted bezier chords the PDF path
    produced.
    """
    from ezdxf import path as ezpath

    try:
        p = ezpath.make_path(entity)
    except Exception as e:
        # NOTE: some entity types aren't path-convertible; skip them.
        print(f"  (skipping {entity.dxftype()}: {e})")
        return []
    pts = [(v.x, v.y) for v in p.flattening(distance=flatten_tol_units)]
    return pts


def is_closed_entity(entity, pts: list[tuple[float, float]]) -> bool:
    """Explicit closed flag if present, else first≈last geometric check."""
    if getattr(entity.dxf, "flags", None) is not None and hasattr(entity, "closed"):
        if entity.closed:
            return True
    if len(pts) >= 4:
        (x0, y0), (xn, yn) = pts[0], pts[-1]
        # tolerance here is in drawing units; CLOSE_TOL_M is converted by caller
        return abs(x0 - xn) <= 1e-6 and abs(y0 - yn) <= 1e-6
    return False


def polygon_area(pts: list[tuple[float, float]]) -> float:
    """Shoelace area (drawing units²), absolute value."""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def collect_loops(doc, layer: str | None, flatten_tol_units: float):
    """
    Return a list of closed loops, each a list of (x, y) points in drawing units.
    Targets LWPOLYLINE/POLYLINE (what a 'closed polyline' export produces);
    CIRCLE/ELLIPSE/SPLINE also flatten fine if present.
    """
    msp = doc.modelspace()
    # NOTE: confirm against the real file which types carry the boundary.
    wanted = ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "SPLINE")
    query = " ".join(wanted)
    loops = []
    for e in msp.query(query):
        if layer and e.dxf.layer != layer:
            continue
        pts = entity_to_points(e, flatten_tol_units)
        if len(pts) < 3:
            continue
        # CIRCLE/ELLIPSE are inherently closed; polylines via flag/geometry.
        closed = e.dxftype() in ("CIRCLE", "ELLIPSE") or is_closed_entity(e, pts)
        if not closed:
            continue
        # Ensure the ring doesn't duplicate the closing point.
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        loops.append({"entity": e.dxftype(), "layer": e.dxf.layer, "pts": pts})
    return loops


def build_blueprint_from_loops(loops, meters_per_unit: float) -> dict:
    """
    Convert closed loops (drawing-unit points) into BlueprintJSON.
    Same output contract and coordinate plane as the PDF tool:
      PDF/DXF (x, y) → planner (x, z); Y held at GROUND_Y.
    """
    if not loops:
        return {"lines": [], "floor": []}

    # Normalize to a (0,0) origin across all kept loops, then scale to meters.
    all_x = [x for lp in loops for (x, _) in lp["pts"]]
    all_y = [y for lp in loops for (_, y) in lp["pts"]]
    min_x, min_y = min(all_x), min(all_y)
    max_x, max_y = max(all_x), max(all_y)
    print(
        f"Extent: {(max_x - min_x) * meters_per_unit:.2f} x "
        f"{(max_y - min_y) * meters_per_unit:.2f} m"
    )

    s = meters_per_unit
    lines: list[dict] = []
    floor: list[dict] = []

    for lp in loops:
        pts = lp["pts"]
        loop_indices = []
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]  # last edge closes back to start
            idx = len(lines)
            lines.append({
                # DXF Y is up (CAD convention) but the planner's top-down view
                # renders +z downward on screen, so map z = (max_y - y) to keep
                # the plan upright instead of mirrored top-to-bottom.
                "start": {"x": round((x1 - min_x) * s, 4), "y": GROUND_Y, "z": round((max_y - y1) * s, 4)},
                "end":   {"x": round((x2 - min_x) * s, 4), "y": GROUND_Y, "z": round((max_y - y2) * s, 4)},
                "thickness": 0.05,
            })
            loop_indices.append(idx)
        floor.append({"loop": loop_indices})

    print(f"Lines: {len(lines)}  Floor loops: {len(floor)}")
    return {"lines": lines, "floor": floor}


def main():
    ap = argparse.ArgumentParser(description="Convert a DXF site plan to Landscape Forms Planner")
    ap.add_argument("dxf_path", help="Path to the DXF file")
    ap.add_argument("--layer", help="Only use entities on this layer (e.g. the property-line layer)")
    ap.add_argument("--units", help="Override units if the DXF is unitless: feet, inches, mm, cm, m, ...")
    ap.add_argument("--all-loops", action="store_true",
                    help="Keep every closed polyline (default: only the largest = site boundary)")
    ap.add_argument("--min-area", type=float, default=0.0, metavar="SQMETERS",
                    help="Drop closed loops below this area in m2 (noise filter)")
    ap.add_argument("--flatten-mm", type=float, default=50.0, metavar="MM",
                    help="Max chord error when tessellating arcs/splines (default 50mm)")
    ap.add_argument("--output", help="Save BlueprintJSON to this file")
    ap.add_argument("--no-browser", action="store_true", help="Don't open the planner URL")
    args = ap.parse_args()

    if not os.path.exists(args.dxf_path):
        print(f"Error: File not found: {args.dxf_path}")
        sys.exit(1)

    import ezdxf
    try:
        doc = ezdxf.readfile(args.dxf_path)
    except (IOError, ezdxf.DXFStructureError) as e:
        print(f"Error reading DXF: {e}")
        sys.exit(1)

    meters_per_unit, unit_label = resolve_units(doc, args.units)
    print(f"Units: {unit_label} -> {meters_per_unit} m/unit")

    # Tessellation tolerance must be expressed in drawing units.
    flatten_tol_units = (args.flatten_mm / 1000.0) / meters_per_unit

    loops = collect_loops(doc, args.layer, flatten_tol_units)
    print(f"Closed loops found: {len(loops)}"
          + (f" on layer '{args.layer}'" if args.layer else ""))
    if not loops:
        print("No closed loops found. Try --layer <name>, or check the DXF has a closed polyline.")
        sys.exit(1)

    # Area annotate + filter (convert unit² → m²).
    for lp in loops:
        lp["area_m2"] = polygon_area(lp["pts"]) * (meters_per_unit ** 2)
    loops.sort(key=lambda lp: lp["area_m2"], reverse=True)
    print("Largest loops (m2):", ", ".join(f"{lp['area_m2']:.4g}" for lp in loops[:5]))

    if args.min_area > 0:
        before = len(loops)
        loops = [lp for lp in loops if lp["area_m2"] >= args.min_area]
        print(f"Kept {len(loops)}/{before} loops at --min-area {args.min_area} m2")

    if not args.all_loops:
        loops = loops[:1]  # the largest closed loop = the site boundary
        print(f"Using largest loop only: {loops[0]['area_m2']:.4g} m2 "
              f"({loops[0]['entity']} on '{loops[0]['layer']}')")

    blueprint = build_blueprint_from_loops(loops, meters_per_unit)

    if args.output:
        import json
        with open(args.output, "w") as f:
            json.dump(blueprint, f, indent=2)
        print(f"Saved BlueprintJSON to {args.output}")

    script = build_inject_script(blueprint)
    copied = copy_to_clipboard(script)

    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print(f"1. Open: {PLANNER_URL}")
    print("2. " + ("Inject script copied to clipboard." if copied else "Copy the script below."))
    print("3. Open DevTools (F12 -> Console), paste, Enter.")
    print("=" * 60)
    if not copied:
        print("\n--- PASTE THIS IN THE BROWSER CONSOLE ---")
        print(script)
        print("--- END ---\n")

    if not args.no_browser:
        webbrowser.open(PLANNER_URL)


if __name__ == "__main__":
    main()
