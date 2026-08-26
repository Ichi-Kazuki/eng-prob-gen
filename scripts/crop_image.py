import argparse
from pathlib import Path
from typing import Iterable

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_IMAGE_DIR = ROOT / 'tmp' / 'pdfs' / 'official'

regions = {
    'B_p4_q26': ('B_p4.png', (80, 160, 800, 260)),
    'C_p3_q16': ('C_p3.png', (900, 130, 1530, 280)),
    'C_p4_q25': ('C_p4.png', (80, 70, 800, 260)),
    'C_p4_q34': ('C_p4.png', (870, 70, 1530, 260)),
    'C_p3_q17_24': ('C_p3.png', (900, 220, 1530, 1030)),
    'C_p4_q25_33': ('C_p4.png', (80, 70, 800, 1040)),
    'C_p4_q34_40': ('C_p4.png', (870, 70, 1530, 1030)),
    'C_p4_q26_spans': ('C_p4.png', (110, 250, 570, 350)),
    'B_p3_q16_25': ('B_p3.png', (900, 160, 1530, 1040)),
    'B_p4_q26_40': ('B_p4.png', (80, 160, 1530, 850)),
    'B_p4_q33_40': ('B_p4.png', (80, 800, 1530, 1030)),
    'E_p3_q22_24': ('E_p3.png', (900, 650, 1530, 1040)),
}

def crop_regions(
    input_dir: Path,
    output_dir: Path,
    selected_regions: Iterable[str] | None = None,
) -> None:
    """Crop the selected named regions without doing work at import time."""
    names = list(selected_regions) if selected_regions is not None else list(regions)
    unknown = sorted(set(names) - set(regions))
    if unknown:
        raise ValueError(f"unknown crop region(s): {', '.join(unknown)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        filename, box = regions[name]
        with Image.open(input_dir / filename) as image:
            image.crop(box).save(output_dir / (name + ".png"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Crop named OCR/reference image regions.")
    parser.add_argument("--input-dir", type=Path, default=OFFICIAL_IMAGE_DIR)
    parser.add_argument("--output-dir", type=Path, default=OFFICIAL_IMAGE_DIR)
    parser.add_argument("--region", action="append", choices=sorted(regions))
    args = parser.parse_args()
    crop_regions(args.input_dir, args.output_dir, args.region)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
