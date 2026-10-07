'''
Check if posters are roughly 1:1.414 landscape.
1. Download all poster PDFs to `IN_DIR`
2. Run this.
'''

import argparse
import math
import re
import subprocess
from pathlib import Path

IN_DIR = './tmp/posters/all'

TARGET_RATIO = math.sqrt(2)  # width / height
TOLERANCE = 0.15  # relative


def page_sizes(path: Path) -> list[tuple[float, float]]:
    '''Return (width, height) in pts of each page, accounting for rotation.'''
    result = subprocess.run(
        ['pdfinfo', '-f', '1', '-l', '-1', str(path)],
        capture_output=True, text=True, check=True,
    )
    sizes = re.findall(r'^Page\s+\d+ size:\s+([\d.]+) x ([\d.]+)', result.stdout, re.MULTILINE)
    rots = re.findall(r'^Page\s+\d+ rot:\s+(\d+)', result.stdout, re.MULTILINE)
    out = []
    for (w, h), rot in zip(sizes, rots):
        w, h = float(w), float(h)
        if int(rot) % 180 == 90:
            w, h = h, w
        out.append((w, h))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--posters', type=Path, default=Path(IN_DIR), help='Poster directory')
    parser.add_argument('--tolerance', type=float, default=TOLERANCE, help='Relative ratio tolerance')
    args = parser.parse_args()

    posters = sorted(args.posters.glob('*.pdf'))
    n_bad = 0
    for path in posters:
        try:
            sizes = page_sizes(path)
        except subprocess.CalledProcessError as exc:
            print(f'Failed to read {path.name}: {exc.stderr.strip()}')
            n_bad += 1
            continue
        problems = []
        if len(sizes) != 1:
            problems.append(f'{len(sizes)} pages')
        if sizes:
            w, h = sizes[0]
            ratio = w / h
            if ratio < 1:
                problems.append('portrait')
            if abs(ratio - TARGET_RATIO) / TARGET_RATIO > args.tolerance:
                problems.append(f'ratio {ratio:.3f} (w/h)')
        if problems:
            n_bad += 1
            print(f'{path.name}: {", ".join(problems)}')
    print(f'{n_bad} / {len(posters)} posters flagged')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
