#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "anthropic>=0.40.0",
#   "pymupdf>=1.24.0",
# ]
# ///
"""
PDF Floor Plan → Landscape Forms Planner

Usage:
  uv run pdf-to-planner.py <path-to-floor-plan.pdf> [--page 0] [--scale 1.0]

What it does:
  1. Renders the PDF page to a PNG image
  2. Sends it to Claude claude-opus-4-8 with a vision prompt to extract walls as BlueprintJSON
  3. Opens the planner in your browser and copies a JS snippet to your clipboard
     that you paste into the browser console to load the floor plan

Requirements:
  - ANTHROPIC_API_KEY env var set
  - uv installed (https://docs.astral.sh/uv/)
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import webbrowser

PLANNER_URL = "https://landscapeforms.planneren.dev/?family=site-planner"

EXTRACTION_PROMPT = """You are analyzing a floor plan image. Extract all walls, boundary lines, and structural edges as a BlueprintJSON object.

Rules:
- All coordinates must be in METERS. If the floor plan shows a scale (e.g. "1 inch = 10 feet"), use it. If not, estimate based on typical room/building sizes.
- Place the origin (0,0,0) at the bottom-left corner of the main structure.
- z is always 0 (this is a 2D top-down floor plan).
- Lines represent walls. Include outer walls and any major interior walls you can identify.
- thickness is wall thickness in meters (typically 0.1–0.3 for interior, 0.2–0.4 for exterior).
- The floor array defines floor regions. Each loop is an ordered list of line indices that form a closed polygon. Index references lines in the lines array (0-based).
- Keep it clean: capture the primary perimeter and main interior walls. Skip furniture, dimensions text, hatching, and annotations.

Return ONLY valid JSON matching this TypeScript type — no explanation, no markdown fences:

{
  "lines": [
    {"start": {"x": number, "y": number, "z": 0}, "end": {"x": number, "y": number, "z": 0}, "thickness": number}
  ],
  "floor": [
    {"loop": [number, number, ...]}
  ]
}

The loop indices must form a valid closed polygon using the lines. Start with the outer building perimeter as the first floor entry."""


def render_pdf_page(pdf_path: str, page_index: int) -> bytes:
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    if page_index >= len(doc):
        print(f"Error: PDF has {len(doc)} pages, requested page {page_index}")
        sys.exit(1)

    page = doc[page_index]
    # Render at 2x resolution for better detail
    mat = fitz.Matrix(2, 2)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def extract_blueprint(image_bytes: bytes) -> dict:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("Sending floor plan to Claude for analysis...")
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Strip markdown fences if Claude added them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


def apply_scale(blueprint: dict, scale: float) -> dict:
    if scale == 1.0:
        return blueprint
    for line in blueprint["lines"]:
        for pt in [line["start"], line["end"]]:
            pt["x"] *= scale
            pt["y"] *= scale
            pt["z"] *= scale
    return blueprint


def build_inject_script(blueprint: dict) -> str:
    bp_json = json.dumps(blueprint)
    return f"""(function() {{
  var bp = {bp_json};
  window.planner.blueprint.fromJSON(bp);
  window.planner.blueprint.render();
  // Auto-click Next after dialog appears, then re-inject the blueprint
  setTimeout(function() {{
    var nextBtn = Array.from(document.querySelectorAll('button')).find(function(b) {{
      return b.textContent.trim() === 'Next';
    }});
    if (nextBtn) {{
      nextBtn.click();
      setTimeout(function() {{
        window.planner.blueprint.fromJSON(bp);
        window.planner.engine.forceRender();
        console.log('Blueprint loaded: ' + bp.lines.length + ' lines, ' + bp.floor.length + ' floor regions');
      }}, 500);
    }} else {{
      console.warn('Could not find Next button — re-injecting anyway');
      window.planner.blueprint.fromJSON(bp);
      window.planner.engine.forceRender();
    }}
  }}, 1000);
}})();"""


def copy_to_clipboard(text: str):
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert a PDF floor plan to Landscape Forms Planner BlueprintJSON"
    )
    parser.add_argument("pdf_path", help="Path to the PDF floor plan")
    parser.add_argument(
        "--page", type=int, default=0, help="Page index to use (0-based, default: 0)"
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Scale multiplier applied to all coordinates (default: 1.0)",
    )
    parser.add_argument(
        "--output",
        help="Optional: save BlueprintJSON to this file path",
    )
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"Error: File not found: {args.pdf_path}")
        sys.exit(1)

    print(f"Rendering page {args.page} of {args.pdf_path}...")
    image_bytes = render_pdf_page(args.pdf_path, args.page)
    print(f"  Rendered: {len(image_bytes):,} bytes")

    blueprint = extract_blueprint(image_bytes)
    blueprint = apply_scale(blueprint, args.scale)

    line_count = len(blueprint.get("lines", []))
    floor_count = len(blueprint.get("floor", []))
    print(f"Extracted: {line_count} lines, {floor_count} floor regions")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(blueprint, f, indent=2)
        print(f"Saved BlueprintJSON to {args.output}")

    inject_script = build_inject_script(blueprint)

    copied = copy_to_clipboard(inject_script)

    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print("1. The planner will open in your browser.")
    if copied:
        print("2. The inject script has been COPIED TO YOUR CLIPBOARD.")
    else:
        print("2. Copy the script below.")
    print("3. Open browser DevTools (Cmd+Option+J on Mac).")
    print('4. Paste into the Console and press Enter.')
    print("=" * 60)

    if not copied:
        print("\n--- PASTE THIS IN THE BROWSER CONSOLE ---")
        print(inject_script)
        print("--- END OF SCRIPT ---\n")

    webbrowser.open(PLANNER_URL)


if __name__ == "__main__":
    main()
