# PDF Floor Plan → Landscape Forms Planner

Convert a PDF floor plan into [Landscape Forms Planner](https://landscapeforms.planneren.dev/?family=site-planner) using Claude AI vision.

## How it works

1. Renders your PDF floor plan to an image
2. Sends it to Claude claude-opus-4-8 to extract walls and boundaries as `BlueprintJSON`
3. Opens the planner in your browser and auto-injects the floor plan

## Requirements

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
