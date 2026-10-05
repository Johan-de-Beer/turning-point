"""Compare browser-composed PNGs; Pillow is a QA-only tool, not an app dependency."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops


def compare(first: Path, second: Path) -> dict:
    with Image.open(first) as source_a, Image.open(second) as source_b:
        a, b = source_a.convert("RGB"), source_b.convert("RGB")
        if a.size != b.size:
            raise ValueError("Frame dimensions changed")
        difference = ImageChops.difference(a, b)
        pixels = list(difference.getdata())
        changed = sum(1 for pixel in pixels if max(pixel) > 0)
        return {"width": a.width, "height": a.height, "changed_pixels": changed,
            "changed_percent": changed / len(pixels) * 100,
            "max_channel_delta": max(max(pixel) for pixel in pixels)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.first, args.second)))
