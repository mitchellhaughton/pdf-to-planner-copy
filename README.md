# DXF Site Plan → Landscape Forms Planner

Convert a **DXF** site plan into the
[Landscape Forms Planner](https://landscapeforms.planneren.dev/?family=site-planner),
deterministically. [`dxf_to_planner.py`](dxf_to_planner.py) reads the real
geometry and units straight from the DXF — no vision model, no guessing, no API
key.

It's a single self-contained script. The only requirement is
[uv](https://docs.astral.sh/uv/), which installs its dependency (`ezdxf`)
automatically on first run.

## Usage

### First time only: install uv

`uv` is what runs the script (it handles Python and the `ezdxf` dependency for
you). Install it once:

- **Windows** (PowerShell):
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **macOS / Linux**:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

Close and reopen your terminal afterward so `uv` is on your PATH. Verify with
`uv --version`.

### Running it

The two lines below are **terminal commands**. Open a terminal — **PowerShell**
on Windows, **Terminal** on macOS/Linux — then `cd` into the folder that
contains `dxf_to_planner.py` (the same folder you downloaded it to):

```bash
cd path/to/folder-with-the-script
```

Now run the two steps, replacing `"site.dxf"` with the path to your own DXF
(quotes matter if the path has spaces):

```bash
# 1. See what layers/geometry the file contains:
uv run dxf_to_planner.py "site.dxf" --list-layers

# 2. Convert the boundary layer (copies an inject script to your clipboard):
uv run dxf_to_planner.py "site.dxf" --layer L-SITE-CONC --simplify 100
```

- **Step 1** prints the layers in the file — find the one holding the site
  boundary and use its name in step 2 (here, `L-SITE-CONC`).
- **Step 2** builds the geometry and **copies an inject script to your
  clipboard**. (The first run may take a few seconds while `uv` downloads
  `ezdxf`.)

Then load it into the planner:

1. Open the [planner](https://landscapeforms.planneren.dev/?family=site-planner)
   in Chrome.
2. Press **F12** to open DevTools, and click the **Console** tab.
3. Click in the console, **paste** (Ctrl/Cmd+V), and press **Enter**. (If Chrome
   blocks the paste, type `allow pasting` and Enter first, then paste again.)

The plan loads in the top-down Plan View.

## Options

| Flag | What it does |
|---|---|
| `--list-layers` | List layers with entity types and closed-loop areas |
| `--layer NAME` | Use only entities on this layer |
| `--all-loops` | Keep every closed loop (default: just the largest) |
| `--stitch` | Assemble open edges (line/arc) into closed loops |
| `--units feet` | Override units if the DXF header is missing/wrong |
| `--simplify 100` | Thin dense vertices (mm of deviation) → fewer dimension tags |
| `--min-area SQM` | Drop closed loops smaller than this (noise filter) |
| `--output out.json` | Also save the raw BlueprintJSON |
| `--no-browser` | Don't open the planner URL automatically |

Run `uv run dxf_to_planner.py --help` for the full list.

## Tips

- **Run `--list-layers` first.** Real architectural files often XREF the
  survey/boundary into separate files, so an export may only contain the host
  drawing's own geometry. If the boundary layer is empty, ask for a DXF with
  XREFs **bound/flattened**.
- **Check the units.** If the plan comes in the wrong size, the DXF's unit header
  may be missing or wrong — override with `--units feet` (or `inches`, `mm`, …).
- **Boundary stored as separate edges?** Add `--stitch` to assemble open
  line/arc segments into closed loops.

## BlueprintJSON format

The planner ingests `BlueprintJSON` (injected via the browser console). All
coordinates are in meters; the ground plane is X-Z with Y up (three.js).

```typescript
type BlueprintJSON = {
  lines: Array<{
    start: { x: number, y: number, z: number }
    end: { x: number, y: number, z: number }
    thickness: number
    color?: [number, number, number]
  }>
  floor: Array<{
    loop: Array<number>  // indices into lines array forming a closed polygon
    color?: [number, number, number]
  }>
}
```

## Helper scripts

- [`make_four_shapes.py`](make_four_shapes.py) / [`make_test_dxf.py`](make_test_dxf.py) — generate small test DXFs.
- [`diagnose_loop.py`](diagnose_loop.py) — check that a DXF's loops are clean ordered rings.

---

_Note: this project originally explored a PDF → planner path (Claude vision, then
deterministic vector extraction). That route was dropped in favor of DXF. The
history lives in [SESSION_NOTES.md](SESSION_NOTES.md) and
[CLEAN_INPUT_PLAN.md](CLEAN_INPUT_PLAN.md) for reference only — those documents
are historical and do not describe the current tool._
