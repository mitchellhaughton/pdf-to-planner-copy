# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pymupdf>=1.24.0",
# ]
# ///
"""List closed-loop bounding-box areas (m²) to inform --min-area tuning."""
import sys
import fitz
from vector_to_planner import is_wall_candidate, is_geometrically_closed

pdf_path = sys.argv[1]
scale = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0423

doc = fitz.open(pdf_path)
page = doc[0]
drawings = page.get_drawings()
walls = [d for d in drawings if is_wall_candidate(d)]

loops = []  # (area_m2, w_m, h_m, n_segments)
for d in walls:
    closed = d.get("closePath", False) or is_geometrically_closed(d)
    if not closed:
        continue
    n_seg = sum(4 if it[0] in ("re", "qu") else 1
                for it in d["items"] if it[0] in ("l", "c", "re", "qu"))
    if n_seg < 3:
        continue
    r = d.get("rect")
    if r is None:
        continue
    w_m, h_m = r.width * scale, r.height * scale
    loops.append((w_m * h_m, w_m, h_m, n_seg))

loops.sort(reverse=True)
print(f"{len(loops)} closed loops with >=3 segments (scale={scale})\n")
print(f"{'area m2':>12} {'w_m':>8} {'h_m':>8} {'segs':>6}")
for a, w, h, n in loops[:25]:
    print(f"{a:12.1f} {w:8.1f} {h:8.1f} {n:6d}")

# Histogram of areas
import bisect
buckets = [0, 1, 5, 10, 20, 50, 100, 500, 1000, 5000, 1e9]
labels = ["<1", "1-5", "5-10", "10-20", "20-50", "50-100", "100-500", "500-1k", "1k-5k", ">5k"]
counts = [0] * (len(buckets) - 1)
for a, *_ in loops:
    counts[bisect.bisect_right(buckets, a) - 1] += 1
print("\nArea histogram (m²):")
for lbl, c in zip(labels, counts):
    print(f"  {lbl:>10}: {c}")
