# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pymupdf>=1.24.0",
# ]
# ///
import sys
import fitz

pdf_path = sys.argv[1] if len(sys.argv) > 1 else "floor-plan.pdf"
doc = fitz.open(pdf_path)
page = doc[0]
drawings = page.get_drawings()

print(f"{len(drawings)} drawing paths found")

type_counts = {}
for d in drawings:
    for item in d["items"]:
        t = item[0]
        type_counts[t] = type_counts.get(t, 0) + 1

print("Item type breakdown:", type_counts)
print()
print("First 5 paths:")
for d in drawings[:5]:
    print(f"  color={d.get('color')} fill={d.get('fill')} width={d.get('width')}")
    for item in d["items"]:
        print(f"    {item[0]}: {item[1:]}")
