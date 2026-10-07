"""
Check videos downloaded by download_and_rename_videos_and_captions.py: warn on long
videos and plot histograms of duration and filesize.
"""

import argparse
import json
import subprocess
from pathlib import Path

from scripts.download_and_rename_videos_and_captions import OUT_DIR


MAX_DURATION = 3 * 60 + 2  # seconds


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)['format']['duration'])


def main() -> int:
    import matplotlib.pyplot as plt  # Lazy so importers of probe_duration skip matplotlib.

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--videos', type=Path, default=OUT_DIR, help='Video directory')
    args = parser.parse_args()

    videos = sorted(path for path in args.videos.iterdir() if path.is_file())
    durations = []
    sizes = []
    for path in videos:
        try:
            duration = probe_duration(path)
        except (subprocess.CalledProcessError, KeyError, ValueError) as exc:
            print(f'Failed to probe {path.name}: {exc}')
            continue
        durations.append(duration)
        sizes.append(path.stat().st_size / 2**20)
        if duration > MAX_DURATION:
            stem, _ = path.name.split('.')
            print(f'Video for paper {stem} is {int(duration // 60)}:{duration % 60:02.0f} long')

    fig, (ax_duration, ax_size) = plt.subplots(1, 2, figsize=(12, 4))
    ax_duration.hist([d / 60 for d in durations], bins=30)
    ax_duration.axvline(MAX_DURATION / 60, color='red', linestyle='--', label='limit')
    ax_duration.set_xlabel('Duration (min)')
    ax_duration.set_ylabel('Videos')
    ax_duration.legend()
    ax_size.hist(sizes, bins=30)
    ax_size.set_xlabel('Filesize (MiB)')
    ax_size.set_ylabel('Videos')
    fig.suptitle(f'{len(durations)} videos')
    fig.tight_layout()
    plt.show()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
