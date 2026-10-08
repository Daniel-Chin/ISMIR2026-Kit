'''
Steps:
1. Download and unzip camera ready paper PDFs from CMT. Each file should start with the paper ID.
2. Run this script. This will verify and copy renamed files into OUT_DIR.
3. When prompted, upload OUT_DIR to a Google Drive Folder which "anyone with the link can view".
4. Paste the folder URL back to this script, which pulls the mapping from paper_id to Google Drive file URL.
5. Paste the updated column "raw_pdf_path" in papers.csv into the Live Database Google Sheet.
'''

import argparse
import csv
import html
import re
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import requests

PAPERS_CSV = './sitedata/papers.csv'
OUT_DIR = './tmp/paper_camera_ready/'

# Plausible camera-ready PDF size range, in bytes.
MIN_BYTES = 1 * 1024
MAX_BYTES = 20 * 1024 * 1024


def collect(in_dir: Path, out_dir: Path, uids: set[int]) -> dict[int, int]:
    '''Copy {paper_id}.pdf into out_dir. Return {paper_id: n_bytes}.'''
    # Leading digits of the filename are the paper ID; the delimiter after them varies.
    by_uid: dict[int, list[Path]] = {}
    for path in in_dir.rglob('*.pdf'):
        if match := re.match(r'\d+', path.name):
            by_uid.setdefault(int(match.group()), []).append(path)

    found: dict[int, Path] = {}
    for uid in sorted(uids):
        paths = by_uid.get(uid, [])
        if len(paths) > 1:
            raise ValueError(f'Duplicate PDFs for paper {uid}: {paths}')
        if paths:
            found[uid] = paths[0]

    out_dir.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for uid, path in sorted(found.items()):
        n_bytes = path.stat().st_size
        sizes[uid] = n_bytes
        if not MIN_BYTES <= n_bytes <= MAX_BYTES:
            print(f'Suspicious size for paper {uid}: {n_bytes} bytes ({path})')
        shutil.copy2(path, out_dir / f'{uid}.pdf')
    if missing := uids - found.keys():
        print(f'Missing PDFs for papers: {sorted(missing)}')
    print(f'{len(found)} / {len(uids)} PDFs copied into {out_dir}')
    return sizes


def list_drive_folder(folder_url: str) -> dict[str, str]:
    '''Return {filename: file_id} of a public Google Drive folder.'''
    match = re.search(r'folders/([\w-]+)', folder_url) or re.search(r'id=([\w-]+)', folder_url)
    if match is None:
        raise ValueError(f'Cannot parse folder ID from {folder_url}')
    # Unlike the regular folder page, the embedded view is not capped at 50 entries.
    response = requests.get(
        'https://drive.google.com/embeddedfolderview',
        params={'id': match.group(1)}, timeout=60,
    )
    response.raise_for_status()
    entries = re.findall(
        r'href="https://drive\.google\.com/file/d/([\w-]+)/[^"]*".*?'
        r'class="flip-entry-title">([^<]*)<',
        response.text, re.DOTALL,
    )
    return {html.unescape(name).strip(): file_id for file_id, name in entries}


def write_raw_pdf_paths(name_to_id: dict[str, str]) -> None:
    with open(PAPERS_CSV, newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source, strict=True)
        headers = reader.fieldnames
        if headers is None or 'raw_pdf_path' not in headers:
            raise ValueError(f'Missing raw_pdf_path column in {PAPERS_CSV}')
        rows = list(reader)
    n_filled = 0
    for row in rows:
        file_id = name_to_id.get(f'{row["uid"]}.pdf')
        if file_id is None:
            print(f'Not found in Drive folder: paper {row["uid"]}')
            continue
        row['raw_pdf_path'] = f'https://drive.google.com/open?id={file_id}'
        n_filled += 1
    with open(PAPERS_CSV, 'w', newline='', encoding='utf-8') as destination:
        writer = csv.DictWriter(destination, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    print(f'raw_pdf_path filled for {n_filled} / {len(rows)} papers in {PAPERS_CSV}')
    print('Please paste the updated raw_pdf_path column into the Live Database Google Sheet.')


def plot_sizes(sizes: dict[int, int]) -> None:
    plt.hist([n / 1024 / 1024 for n in sizes.values()], bins=40)
    plt.xlabel('File size (MB)')
    plt.ylabel('# papers')
    plt.title(f'Camera-ready PDF sizes (n={len(sizes)})')
    plt.show()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('in_dir', type=Path, help='Directory of unzipped CMT camera-ready PDFs')
    parser.add_argument('--out', type=Path, default=Path(OUT_DIR), help='Output directory')
    args = parser.parse_args()

    with open(PAPERS_CSV, newline='', encoding='utf-8') as source:
        uids = {int(row['uid']) for row in csv.DictReader(source)}
    sizes = collect(args.in_dir, args.out, uids)

    print(f'Now upload {args.out.resolve()} to a Google Drive folder that "anyone with the link can view".')
    folder_url = input('Paste the folder URL: ').strip()
    write_raw_pdf_paths(list_drive_folder(folder_url))

    plot_sizes(sizes)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
