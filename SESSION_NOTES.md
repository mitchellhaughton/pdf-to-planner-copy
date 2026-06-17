# Session Notes: Vector Pipeline Progress

## What we built

`vector_to_planner.py` — a deterministic replacement for the vision step in
`pdf-to-planner.py`. Instead of rasterizing the PDF and asking Claude to guess
geometry, it extracts real vector paths via `page.get_drawings()` and converts
them directly to BlueprintJSON.

Run it the same way as the original script:
```
uv run vector_to_planner.py "path/to/floor-plan.pdf" --scale 0.0423
```

## Test PDF: L101-02.pdf

- **File:** `C:\Users\Haugh\Downloads\L101-02.pdf`
- **Description:** MGB Westborough, MA — Layout and Materials Plan (Enlargement),
  Gensler, project MYKD 5019-01. Sheet L101-02.
- **Drawing scale:** `1" = 10'-0"`  →  `--scale 0.0423`
- **Page size:** 3456 × 2592 pts (48" × 36", ANSI D)
- **Total vector paths:** 73,842
- **After wall-candidate filter:** 8,750 paths → 20,246 line segments
- **Floor loops found:** 300 (all geometrically closed; none have `closePath=True`,
  which is normal for CAD exports)
- **Real-world extent at correct scale:** ~104m × 137m

## Key findings from diagnostics

| Finding | Detail |
|---|---|
| PDF is fully vector | `get_drawings()` returns 73k paths — not a scanned raster |
| `closePath` never set | All closed paths are open polylines that return to start; detected via geometric check |
| Coordinates outside page bounds | Some paths (title block area) have y > page height, causing negative values after naive Y-flip |
| Fix | Removed Y-flip; normalize all coords to (0,0) origin after collection |

## How the converter works

1. **Filter** — keeps only stroked paths (`color != None`, `width >= 0.5pt`).
   Drops fill-only paths (hatching, shading).
2. **Segment extraction** — `l` items → lines; `c` beziers → straight chord
   approximation; `re` rects → 4 edges; `qu` quads → 4 edges.
3. **Geometric close detection** — if a path's last endpoint is within
   `SNAP_TOLERANCE=1.0pt` of its first point, it's treated as a closed loop
   and emitted as a `floor[]` entry.
4. **Normalization** — after all segments collected, subtract `(min_x, min_y)`
   so origin is (0,0), then multiply by `--scale` to get meters.

## Current state: blueprint IS loading

The inject script works end-to-end:
- 20,246 lines + 300 floor regions load into the planner
- Console confirms: `Blueprint loaded: 20246 lines, 300 floor regions`
- Canvas renders a shape

## DXF input path (sketched 2026-06-17): `dxf_to_planner.py`

Preferred pipeline IF the drawing's author can supply a DXF. A DXF carries
real-world UNITS (scale is read, not guessed) and the site boundary as a single
CLOSED polyline (no stitching needed). What to request from the author:
**"site/property boundary as a DXF, ideally a single closed polyline on its own
layer, and tell me the units."**

`dxf_to_planner.py` reuses the inject/clipboard/browser plumbing from
`vector_to_planner.py` (imports `build_inject_script`, `copy_to_clipboard`,
`PLANNER_URL` — works because `import fitz` there is lazy). It:
- reads `$INSUNITS` → meters/unit (override with `--units feet` if unitless);
- collects closed LWPOLYLINE/POLYLINE/CIRCLE/ELLIPSE/SPLINE via `ezdxf.path`
  flattening (arcs/bulges/splines tessellate smoothly — no faceting);
- `--layer NAME` to target a layer, `--min-area`, `--all-loops` (default = keep
  only the largest loop = site boundary);
- emits the same BlueprintJSON in the correct ground plane (x, z; y=GROUND_Y).

**Status:** validated end-to-end on a synthetic DXF (100×200 ft rectangle →
30.48×60.96 m, units auto-read, layer/area filters work) AND on a real
spline-based DXF (heart/paws clipart, mm units, 6 closed loops) — rendered flat
& smooth in the planner, confirming the full DXF→planner chain incl. SPLINE
flattening. (Note: `--all-loops` fills every loop as a separate floor face;
default single-largest-loop mode is the right choice for a site boundary.)
✅ Y-FLIP RESOLVED: DXF is Y-up but the planner renders +z downward, so the plan
came in mirrored top-to-bottom. Fixed by mapping z = (max_y - y). Confirmed with
a 4-shape test DXF (pentagon/diamond/hexagon/point-down gem) — orientation now
matches the source. `make_four_shapes.py` regenerates it; `diagnose_loop.py`
checks that flattened loops are clean ordered rings (no jump/closing-chord).

Remaining DXF unknowns (only verifiable on a real architectural DXF): which
entity types actually carry the boundary, and real layer names.
`make_test_dxf.py` regenerates the rectangle smoke-test fixture.

## ✅ Coordinate-plane bug FIXED + planner format confirmed (2026-06-17)

**Root cause of the "vertical wall":** the planner uses three.js convention —
**Y is UP, ground plane is X-Z**. A clean preset silhouette dumps as
`{x, y: 0.01, z}` (y constant). Our converter emitted `{x, y, z: 0}`, putting the
2D drawing in the vertical X-Y plane → it stood up like a wall. Fixed: map PDF
(x, y) → planner (x, z) with constant `GROUND_Y = 0.01`.

**Confirmed clean format** (preset Silhouette A): 6 lines + 1 floor loop
`[0..5]`; planner traces a polygon from the loop's (undirected) edges;
`lineLengths[]` drives the "Sides" panel. So the planner wants ONE clean closed
loop, not interior linework.

**Added `--loops-only`:** keep only segments belonging to a floor[] loop
(reindexed), drop all other linework. With `--min-area 10 --loops-only` the
L101-02 inject is 26 lines / 2 loops and renders **flat and clean** (building
footprint ≈ 34×61m + one small square). Format is now correct end-to-end.

Recommended invocation:
`uv run vector_to_planner.py "...L101-02.pdf" --scale 0.0423 --min-area 10 --loops-only`

## ⚠️ Architectural finding (2026-06-17): planner wants a SITE OUTLINE, not linework

Tested the full inject in the live planner. Confirmed via the UI ("Change Site
Shape and/or Dimensions", "Silhouette A/B/C", a "Dimensions" list of editable
**Sides**) that this is a **site planner**: its blueprint is meant to be a
**single clean closed site-boundary polygon** that you place landscape products
inside — NOT a dump of interior wall lines.

Injecting all 16,400 line segments makes the planner try to treat the whole
linework as one site boundary → renders as a garbled tall black mass with
thousands of "Side <lineIndex>" labels. The geometry & scale are correct in the
model (extent 104.3m × 137.1m, matches expected), so this is an *input-shape*
mismatch, not a scale bug.

Implication: the high-value extraction target is the **outer site boundary as
one closed loop** (task #4 below), injected as the sole/primary floor region —
not "every wall-candidate line". min-area was necessary cleanup but not
sufficient.

Also fixed: inject script now clicks **"Plan View"** (the planner removed the old
"Next" button) so future runs land on the top-down view automatically.

## What still needs work

### 1. Too many / wrong floor regions  ✅ DONE (`--min-area`)
Added `--min-area SQMETERS` filter. Applies **only to closed loops** (candidate
floor regions) — open polylines (walls) are never area-filtered, because an
axis-aligned wall has a near-zero bounding-box height and would be wrongly
dropped. Uses `d["rect"]` bbox area × scale².

**Area distribution for L101-02 (scale 0.0423)** — see `diagnose_areas.py`:
- Exactly **one** large closed loop: **1,810 m²** (34×53m, 22 segs) = building footprint.
- Everything else ≤ 4.8 m² (21 loops 1–5 m², 265 loops < 1 m²) = plant symbols,
  detail markers, hatch boxes.
- There is a ~1,800 m² gap, so any `--min-area` from 10 to 1000 cleanly isolates
  the real region(s). **Recommended: `--min-area 10`** → 2 floor loops kept,
  298 dropped, lines 20,246 → 16,400.

**Important finding:** the outer **site boundary is NOT a closed loop** — the
largest region is only 1,810 m² but the site is ~14,000 m² (104×137m). The
curved boundary is an *open* polyline (bezier segments), so it never becomes a
floor[] loop and `--min-area` can't surface it. See task #3 (bezier) and #4
(stitching) — those are what's needed to capture the site outline.

### 2. Scale confirmation
The `--scale 0.0423` value is correct for this drawing (`1" = 10'-0"`).
Need to verify in the planner that Site Details shows ~104m wide (or ~340ft).

### 3. Bezier curves approximated as straight chords
The outer site boundary has curved edges (visible in the PDF). Currently `c`
(cubic bezier) items are approximated as a single straight line from start to
end. This will make curved boundaries look faceted/choppy.

**Proposed fix:** Subdivide bezier curves into N short straight segments
(e.g. 8 segments per curve). PyMuPDF also exposes `page.get_cdrawings()` which
returns curves pre-tessellated.

### 4. Floor loop validity
The planner requires `floor[].loop` to be indices of lines that form a
**connected chain** (each line's endpoint == next line's start). For paths with
skipped zero-length segments, there can be index gaps. Not confirmed as a
rendering issue yet, but worth auditing if shapes render incorrectly.

## Next session starting point

1. Run `uv run vector_to_planner.py "C:\Users\Haugh\Downloads\L101-02.pdf" --scale 0.0423 --min-area 10`
   and paste into planner. Confirm dimensions read ~104m wide.
2. ✅ `--min-area` filter added (see task #1 above). Default recommendation 10 m².
3. Improve bezier handling — curved boundary edges are faceted (straight chords).
4. **Capture the site boundary.** It's an *open* polyline, not a closed loop, so
   it never reaches floor[]. Need to stitch the boundary path segments into a
   closed loop (and/or subdivide its beziers) before it can become a floor region.

## uv / environment

- uv installed at `C:\Users\Haugh\.local\bin\uv.exe`
- Python 3.12.13 managed by uv at `C:\Users\Haugh\AppData\Roaming\uv\python\cpython-3.12.13-...`
- Run all scripts with: `$env:Path = "C:\Users\Haugh\.local\bin;$env:Path"; uv run <script>`
  (or add `C:\Users\Haugh\.local\bin` to your system PATH permanently)
- pymupdf installs automatically via the `# dependencies` inline script metadata
