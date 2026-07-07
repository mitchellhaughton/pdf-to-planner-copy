# Plan: Clean Input for the Floor Planner

> ⚠️ **HISTORICAL — not the current tool.** This is the original planning doc for
> moving off Claude vision toward deterministic vector extraction from PDFs. The
> project ultimately went the **DXF route** (`dxf_to_planner.py`) and all PDF
> code was removed. Kept for reference only; see [README.md](README.md) for the
> current tool.

## TL;DR

The accuracy problem is **not** that the input is a PDF. It's that the script
rasterizes the PDF to a PNG (`page.get_pixmap()`) and asks a vision model to
*guess* the geometry back out of pixels — including estimating scale "based on
typical room sizes" when no scale is present. That guessing step is where
accuracy is lost. Feeding a cleaner vector won't help while it's still flattened
to an image first.

Also note: **the planner does not ingest a vector file in any format.** Its only
ingestion path is `BlueprintJSON` injected via the browser console
(`window.planner.blueprint.fromJSON()`). The vector is an *intermediate the
script parses* — the format question is about what's easiest/most accurate for
our script to parse, not about the planner.

## Current pipeline (and where it breaks)

1. PDF → `page.get_pixmap(matrix=2x)` → PNG  ← **vector data discarded here**
2. PNG → Claude Opus vision → `BlueprintJSON`  ← **coordinates + scale guessed**
3. `BlueprintJSON` → console injection → planner

Confidence:
- [Certain] Rasterization throws away any vector geometry the PDF contains.
- [Certain] The prompt instructs the model to estimate scale when none is given.
- [Likely] The planner has no native file import; injection is the only path.

## Proposed approach

**Extract real vector geometry and convert it deterministically. Remove the
vision model from the geometry step entirely.**

PyMuPDF (already a dependency) exposes `page.get_drawings()`, which returns the
actual path objects — lines, rectangles, curves — in PDF point coordinates. If
the PDF is already vector (most CAD/architectural exports are), the input file
doesn't need to change at all. Replace `get_pixmap` → vision with
`get_drawings` → deterministic transform.

### Source format options, ranked by accuracy

1. **DXF** — best if obtainable. CAD-native, carries real-world units, which
   solves scale outright. Parse with `ezdxf`. Ask the plan's author whether they
   can export DXF.
2. **Vector PDF** — current input is likely fine *if* it's vector. Test it (see
   below). Replace the rasterize step with `get_drawings()`.
3. **SVG** — easy to parse (`svgpathtools` / `xml.etree`) but unitless/pixel-
   based, so it inherits the same scale ambiguity as a PDF and gains nothing
   over option 2.

### The hard part: scale

Geometry in PDF points or SVG pixels still needs one real-world scale factor to
become meters. A vector fixes *shape* accuracy but not *size* accuracy. Source
the scale factor from one of:
- Real units from DXF (cleanest), or
- A known dimension the user supplies (e.g. "south wall = 12.0 m" → compute the
  factor), or
- A scale bar in the drawing (click two points).

Make scale **explicit/required** rather than estimated. The existing `--scale`
flag is a crude manual version of this.

## Concrete steps

1. **Diagnose the source.** Run `get_drawings()` on a real PDF and check whether
   it returns many path items (vector) or near-nothing (scanned raster, where
   vision is unavoidable).
2. **Add a `--vector` path.** Call `get_drawings()` instead of rendering.
3. **Write a deterministic converter:**
   - Path segments → `lines[]`. Dedupe shared endpoints; snap near-coincident
     points so loops actually close.
   - Build `floor[]` loops from closed path sequences (references line indices).
     Closing loops cleanly is the fiddly part — the planner needs valid closed
     polygons.
   - Flip Y if needed: PDF origin is top-left; `BlueprintJSON` wants bottom-left.
4. **Make scale explicit** via known dimension or DXF units.
5. **Keep the vision path as a fallback** only for genuinely scanned/raster plans.

## Open question (blocks the clean path)

Can we get the source as **DXF**, or at least confirm the PDFs are **vector**?
That determines whether this becomes a fully deterministic pipeline or stays
partially dependent on the model.

## Diagnostic snippet (to run first)

```python
import fitz  # PyMuPDF

doc = fitz.open("path/to/floor-plan.pdf")
page = doc[0]
drawings = page.get_drawings()
print(f"{len(drawings)} drawing paths found")
# Many paths -> vector (good). ~0 -> scanned raster (vision still needed).
for d in drawings[:5]:
    for item in d["items"]:
        print(item[0], item[1:])  # 'l'=line, 're'=rect, 'c'=curve, 'qu'=quad
```
