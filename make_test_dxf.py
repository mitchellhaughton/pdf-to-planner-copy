# /// script
# requires-python = ">=3.11"
# dependencies = ["ezdxf>=1.1"]
# ///
"""Throwaway: emit a tiny DXF (closed rectangle + a small inner box) in feet
to smoke-test dxf_to_planner.py without a real drawing."""
import ezdxf

doc = ezdxf.new()
doc.header["$INSUNITS"] = 2  # feet
msp = doc.modelspace()

# Outer "site boundary": 100ft x 200ft closed polyline on layer C-PROP
msp.add_lwpolyline(
    [(0, 0), (100, 0), (100, 200), (0, 200)],
    close=True,
    dxfattribs={"layer": "C-PROP"},
)
# Small inner box (noise) on another layer — 10ft x 10ft
msp.add_lwpolyline(
    [(40, 40), (50, 40), (50, 50), (40, 50)],
    close=True,
    dxfattribs={"layer": "DETAIL"},
)
doc.saveas("test_site.dxf")
print("wrote test_site.dxf")
