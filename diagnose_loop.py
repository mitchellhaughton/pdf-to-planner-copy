# /// script
# requires-python = ">=3.11"
# dependencies = ["ezdxf>=1.1"]
# ///
"""Check whether a DXF's flattened loops are clean ordered rings.
A big max-edge relative to perimeter/sqrt(area) => disordered points or a
spurious closing chord (i.e. OUR bug). Small => clean ring (spikes are the
planner's concave fill, not us)."""
import sys, math
import ezdxf
from dxf_to_planner import collect_loops, resolve_units, polygon_area

path = sys.argv[1]
doc = ezdxf.readfile(path)
mpu, _ = resolve_units(doc, None)
flat_tol = (0.05 / 1.0) / mpu  # ~50mm chord tol in drawing units

loops = collect_loops(doc, None, flat_tol)
for lp in loops:
    lp["area_m2"] = polygon_area(lp["pts"]) * mpu * mpu
loops.sort(key=lambda l: l["area_m2"], reverse=True)

print(f"{len(loops)} loops; units {mpu} m/unit\n")
for i, lp in enumerate(loops[:4]):
    pts = lp["pts"]
    n = len(pts)
    edges = [math.dist(pts[k], pts[(k + 1) % n]) for k in range(n)]
    perim = sum(edges)
    max_e = max(edges)
    diag = math.dist(
        (min(p[0] for p in pts), min(p[1] for p in pts)),
        (max(p[0] for p in pts), max(p[1] for p in pts)),
    )
    print(f"loop {i}: {n} pts, area={lp['area_m2']:.4g} m2")
    print(f"  perimeter={perim:.3f}u  bbox-diag={diag:.3f}u")
    print(f"  max edge={max_e:.3f}u  ({100*max_e/diag:.1f}% of bbox diagonal)")
    # A clean tessellated ring has every edge << bbox. >40% of the diagonal in a
    # single edge means a jump/closing chord across the shape.
    flag = "  <-- SUSPICIOUS: long edge, likely a jump/closing chord" if max_e > 0.4 * diag else "  OK: smooth ring"
    print(flag)
