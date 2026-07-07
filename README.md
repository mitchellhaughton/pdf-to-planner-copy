# PDF Floor Plan → Landscape Forms Planner

Convert a PDF floor plan into [Landscape Forms Planner](https://landscapeforms.planneren.dev/?family=site-planner) using Claude AI vision.

## How it works

1. Renders your PDF floor plan to an image
2. Sends it to Claude claude-opus-4-8 to extract walls and boundaries as `BlueprintJSON`
3. Opens the planner in your browser and auto-injects the floor plan

## DXF site plans (recommended, deterministic — no API key needed)

If you have the site plan as a **DXF**, use [`dxf_to_planner.py`](dxf_to_planner.py)
instead. It reads the real geometry and units directly — no vision model, no
guessing, no Anthropic key. It's a single self-contained file; the only
requirement is [uv](https://docs.astral.sh/uv/), which installs its dependency
(ezdxf) automatically on first run.

```bash
# 1. See what layers/geometry the file contains:
uv run dxf_to_planner.py "site.dxf" --list-layers

# 2. Convert the boundary layer (copies an inject script to your clipboard):
uv run dxf_to_planner.py "site.dxf" --layer L-SITE-CONC --simplify 100
```

Then open the [planner](https://landscapeforms.planneren.dev/?family=site-planner)
in Chrome, press F12 → Console, paste (Ctrl/Cmd+V), Enter. (If Chrome blocks it,
type `allow pasting` first.) The plan loads in the top-down Plan View.

Useful flags:

| Flag | What it does |
|---|---|
| `--list-layers` | List layers with entity types and closed-loop areas |
| `--layer NAME` | Use only entities on this layer |
| `--all-loops` | Keep every closed loop (default: just the largest) |
| `--stitch` | Assemble open edges (line/arc) into closed loops |
| `--units feet` | Override units if the DXF header is missing/wrong |
| `--simplify 100` | Thin dense vertices (mm) → fewer dimension tags |
| `--output out.json` | Also save the raw BlueprintJSON |

Run `uv run dxf_to_planner.py --help` for the full list.

## Requirements (PDF + vision path below)

- [uv](https://docs.astral.sh/uv/) — Python package runner
- An [Anthropic API key](https://console.anthropic.com/settings/api-keys)

## Setup

Install uv (one-time):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Set your API key (add to `~/.zshrc` to make it permanent):
```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

## Usage

```bash
uv run pdf-to-planner.py "path/to/floor-plan.pdf"
```

Then paste the copied script into the browser DevTools console (Cmd+Option+J → Console) and press Enter. The floor plan loads automatically.

### Options

```
--page 0        # Which PDF page to use (0-based, default: first)
--scale 1.0     # Multiply all coordinates by this factor (tweak if sizing is off)
--output out.json  # Also save the raw BlueprintJSON to a file
```

## BlueprintJSON format

All coordinates are in meters.

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
