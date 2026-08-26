from pathlib import Path
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
for name, (filename, box) in regions.items():
    image = Image.open(OFFICIAL_IMAGE_DIR / filename)
    image.crop(box).save(OFFICIAL_IMAGE_DIR / (name + '.png'))
