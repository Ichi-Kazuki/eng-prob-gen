import argparse
import json
from pathlib import Path
from typing import Sequence

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_IMAGE_DIR = ROOT / 'tmp' / 'pdfs' / 'official'
OCR_BOX_DIR = ROOT / 'tmp' / 'pdfs' / 'official_ocr_boxes'

def row_runs(image, y, x0, x1, threshold=200, max_gap=3, min_width=5):
    runs = []
    start = None
    last_black = None
    for x in range(x0, x1):
        black = image.getpixel((x, y)) < threshold
        if black:
            if start is None:
                start = x
            last_black = x
        elif start is not None and x - last_black > max_gap:
            if last_black + 1 - start >= min_width:
                runs.append((start, last_black + 1))
            start = None
            last_black = None
    if start is not None and last_black + 1 - start >= min_width:
        runs.append((start, last_black + 1))
    return runs

def candidates(image, y0, y1, x0, x1):
    groups = []
    for y in range(y0, y1):
        for start, end in row_runs(image, y, x0, x1):
            matches = [g for g in groups if y - g['last_y'] <= 2 and not (end < g['start'] - 4 or start > g['end'] + 4)]
            if matches:
                g = matches[0]
                g['start'] = min(g['start'], start)
                g['end'] = max(g['end'], end)
                g['top'] = min(g['top'], y)
                g['bottom'] = max(g['bottom'], y)
                g['last_y'] = y
            else:
                groups.append({'start': start, 'end': end, 'top': y, 'bottom': y, 'last_y': y})
    return [g for g in groups if g['end'] - g['start'] >= 8 and g['bottom'] - g['top'] <= 6]

def inspect(name: str, image_dir: Path = OFFICIAL_IMAGE_DIR, ocr_box_dir: Path = OCR_BOX_DIR) -> None:
    with Image.open(image_dir / f'{name}.png') as source_image:
        image = source_image.convert('L')
    payload = json.loads((ocr_box_dir / f'{name}.json').read_text(encoding='utf-8-sig'))
    for line in payload['lines']:
        words = line['words']
        if not words:
            continue
        min_y = int(min(w['y'] for w in words))
        max_y = int(max(w['y'] + w['height'] for w in words))
        min_x = int(min(w['x'] for w in words))
        max_x = int(max(w['x'] + w['width'] for w in words))
        if min_y < 170 or min_y > 1000:
            continue
        found = candidates(image, max(0, min_y + 8), min(image.height, max_y + 5), max(85, min_x - 5), min(image.width, max_x + 5))
        if found:
            print('LINE', line['text'][:60], 'y', min_y, max_y, 'candidates', found)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect likely underlines in an OCR image.")
    parser.add_argument("name", nargs="?", default="B_p4")
    parser.add_argument("--image-dir", type=Path, default=OFFICIAL_IMAGE_DIR)
    parser.add_argument("--ocr-box-dir", type=Path, default=OCR_BOX_DIR)
    args = parser.parse_args(argv)
    inspect(args.name, args.image_dir, args.ocr_box_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
