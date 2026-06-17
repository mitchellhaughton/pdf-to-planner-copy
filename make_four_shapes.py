# /// script
# requires-python = ">=3.11"
# dependencies = ["ezdxf>=1.1"]
# ///
"""Generate a DXF with 4 closed polylines matching the reference image:
pentagon (top-left), diamond (top-right), hexagon (bottom-left),
gem (bottom-right). Units = meters; shapes ~5 m, 2x2 grid."""
import math
import ezdxf

R = 2.5          # shape "radius" in meters
DX, DY = 8.0, 8.0  # grid spacing between quadrant centers


def regular_polygon(cx, cy, n, r, start_deg):
    """n-gon vertices, first vertex at start_deg, counter-clockwise."""
    pts = []
    for i in range(n):
        a = math.radians(start_deg + i * 360.0 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


doc = ezdxf.new()
doc.header["$INSUNITS"] = 6  # meters
msp = doc.modelspace()

# Top-left: regular pentagon, point up
pentagon = regular_polygon(0, DY, 5, R, 90)

# Top-right: diamond = square rotated 45 deg (vertices at top/right/bottom/left)
diamond = regular_polygon(DX, DY, 4, R, 90)

# Bottom-left: hexagon, pointy-top (vertical left/right edges)
hexagon = regular_polygon(0, 0, 6, R, 90)

# Bottom-right: point-down gem (flat top, beveled shoulders, bottom point)
gx, gy = DX, 0
gem = [
    (gx - 2.2, gy + 1.8),   # top-left
    (gx + 2.2, gy + 1.8),   # top-right
    (gx + 2.6, gy + 0.6),   # right shoulder
    (gx + 0.0, gy - 2.6),   # bottom point
    (gx - 2.6, gy + 0.6),   # left shoulder
]

for name, pts in [("PENTAGON", pentagon), ("DIAMOND", diamond),
                  ("HEXAGON", hexagon), ("GEM", gem)]:
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": name})

out = r"C:\Users\Haugh\Downloads\four-shapes.dxf"
doc.saveas(out)
print(f"wrote {out}")
print(f"  pentagon: {len(pentagon)} verts, diamond: {len(diamond)}, "
      f"hexagon: {len(hexagon)}, gem: {len(gem)}")
