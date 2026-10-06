"""
Download public Google Drive videos sequentially, naming them by paper uid.  
"""

import argparse
import csv
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import gdown
from tqdm import tqdm


ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / 'sitedata/papers.csv'
OUT_DIR = ROOT / 'tmp/videos'


def atomic_write(path: Path, contents: str) -> None:
    """Replace a state file without exposing partially written contents."""
    with TemporaryDirectory(dir=path.parent, prefix='.write-') as temp:
        staged = Path(temp) / path.name
        with staged.open('w', encoding='utf-8') as target:
            target.write(contents)
            target.flush()
            os.fsync(target.fileno())
        staged.replace(path)


def download_videos(in_csv: Path, out_dir: Path) -> int:
    """Track local URLs and log successful downloads; skip blank video cells.

    download-state/video_urls.json records URLs of downloaded local files.
    download-state/new_videos.log is replaced each run with successful UIDs,
    one per line (including first downloads). Run only one downloader at a time.
    """
    with in_csv.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if not {'uid', 'raw_video'} <= set(reader.fieldnames or []):
            raise ValueError('CSV must contain uid and raw_video columns')
        videos = [
            ((row.get('uid') or '').strip(), (row['raw_video'] or '').strip())
            for row in reader
            if (row.get('raw_video') or '').strip()
        ]

    seen = set()
    for paper_id, _ in videos:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', paper_id):
            raise ValueError(f'Invalid paper uid: {paper_id!r}')
        if paper_id in seen:
            raise ValueError(f'Duplicate paper uid: {paper_id!r}')
        seen.add(paper_id)

    out_dir.mkdir(parents=True, exist_ok=True)
    state_dir = out_dir / 'download-state'
    state_dir.mkdir(exist_ok=True)
    urls_path = state_dir / 'video_urls.json'
    local_urls = json.loads(urls_path.read_text(encoding='utf-8')) if urls_path.exists() else {}
    if not isinstance(local_urls, dict) or not all(
        isinstance(uid, str) and isinstance(url, str) for uid, url in local_urls.items()
    ):
        raise ValueError(f'Invalid video URL map: {urls_path}')
    atomic_write(urls_path, json.dumps(local_urls, indent=2, sort_keys=True) + '\n')
    new_videos = []
    failures = 0
    skipped = 0
    pending = []
    for paper_id, url in videos:
        try:
            local_files = [
                path for path in out_dir.glob(f'{paper_id}.*')
                if path.stem == paper_id and path.is_file()
            ]
            if local_urls.get(paper_id) == url and any(
                path.stat().st_size >= 1024 for path in local_files
            ):
                skipped += 1
                continue
            pending.append((paper_id, url, local_files))
        except Exception as exc:
            failures += 1
            tqdm.write(f'Failed uid={paper_id}: {exc}')

    consecutive_failures = 0
    attempted = 0
    with tqdm(pending, desc='Videos', unit='video') as progress:
        for paper_id, url, local_files in progress:
            attempted += 1
            progress.set_postfix_str(f'uid={paper_id}')
            try:
                # Persist invalidation before touching any existing video.
                local_urls.pop(paper_id, None)
                atomic_write(urls_path, json.dumps(local_urls, indent=2, sort_keys=True) + '\n')
                for path in local_files:
                    path.unlink()
                # Retain Drive's filename until its extension is known. Only
                # publish the final name once the download has completed.
                with TemporaryDirectory(dir=out_dir, prefix=f'.{paper_id}-') as temp:
                    downloaded = gdown.download(
                        url=url,
                        output=temp + os.sep,
                        fuzzy=True,
                        quiet=True,
                        use_cookies=False,
                    )
                    if downloaded is None:
                        raise RuntimeError('Google Drive download failed')
                    video = Path(downloaded)
                    if not video.suffix:
                        raise ValueError('Google Drive filename has no extension')
                    if video.stat().st_size < 1024:
                        raise ValueError('Downloaded video is smaller than 1024 bytes')
                    video.replace(out_dir / f'{paper_id}{video.suffix}')
                updated_urls = {**local_urls, paper_id: url}
                atomic_write(urls_path, json.dumps(updated_urls, indent=2, sort_keys=True) + '\n')
                local_urls = updated_urls
                new_videos.append(paper_id)
                consecutive_failures = 0
            except Exception as exc:
                failures += 1
                consecutive_failures += 1
                tqdm.write(f'Failed uid={paper_id}: {exc}')
                if consecutive_failures >= 3:
                    tqdm.write('Stopping after 3 consecutive failures.')
                    break

    atomic_write(state_dir / 'new_videos.log', ''.join(f'{uid}\n' for uid in new_videos))
    tqdm.write(
        f'Downloaded {len(new_videos)} videos to {out_dir}; '
        f'skipped {skipped}, failed {failures}, not attempted {len(pending) - attempted}'
    )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=IN_CSV, help='Input CSV path')
    parser.add_argument('--output', type=Path, default=OUT_DIR, help='Video output directory')
    args = parser.parse_args()
    return 1 if download_videos(args.input, args.output) else 0


if __name__ == '__main__':
    raise SystemExit(main())
