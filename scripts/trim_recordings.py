"""Trim Zoom recordings in ~/Downloads into per-session folders.

Usage:
  python scripts/trim_recordings.py 20261109 day-1 \
      074058:oral-session-2:1m: 091516:oral-session-3:1h13m:1h53m

Each job is <recording HHMMSS>:<session-name>:<start>:<end>; empty end = to the end.
Times accept 1h13m / 20m / 90s / plain seconds.
Writes /home/dan/ismir2026/recordings/<day>/<name>/<name>-{video.mp4,audio.m4a,transcript.vtt,cc.vtt}.
Video is re-encoded for frame-exact cuts; audio is stream-copied; VTT cues are shifted/clipped.
"""
import glob
import os
import re
import subprocess
import sys

DOWNLOADS = os.path.expanduser('~/Downloads')
OUT_ROOT = '/home/dan/ismir2026/recordings'


def parse_duration(s: str) -> float:
    if re.fullmatch(r'[\d.]+', s):
        return float(s)
    m = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?', s)
    if not m or not s:
        raise ValueError(f'bad time: {s}')
    h, mi, se = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + float(se or 0)


def vtt_timestamp_to_seconds(s: str) -> float:
    h, m, x = s.split(':')
    return int(h) * 3600 + int(m) * 60 + float(x)


def seconds_to_vtt_timestamp(t: float) -> str:
    return '%02d:%02d:%06.3f' % (t // 3600, t % 3600 // 60, t % 60)


def trim_vtt(src: str, dst: str, start: float, end: float | None) -> None:
    blocks = open(src).read().strip().split('\n\n')
    out = ['WEBVTT']
    for block in blocks[1:]:
        lines = block.split('\n')
        i = next(k for k, line in enumerate(lines) if '-->' in line)
        s, e = (vtt_timestamp_to_seconds(x.strip()) for x in lines[i].split('-->'))
        if e <= start or (end is not None and s >= end):
            continue
        s = max(s, start) - start
        e = (e if end is None else min(e, end)) - start
        out.append('%d\n%s --> %s\n%s' % (
            len(out), seconds_to_vtt_timestamp(s), seconds_to_vtt_timestamp(e), '\n'.join(lines[i + 1:]),
        ))
    open(dst, 'w').write('\n\n'.join(out) + '\n')


def trim(date: str, day: str, rec_id: str, name: str, start: float, end: float | None) -> None:
    out_dir = f'{OUT_ROOT}/{day}/{name}'
    os.makedirs(out_dir, exist_ok=True)
    prefix = f'{DOWNLOADS}/GMT{date}-{rec_id}_Recording'
    cut = ['-ss', str(start)] + ([] if end is None else ['-to', str(end)])
    videos = [v for v in glob.glob(prefix + '_*.mp4') if os.path.getsize(v)]
    if videos:
        subprocess.run([
            'ffmpeg', '-y', '-v', 'error', *cut, '-i', videos[0],
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
            f'{out_dir}/{name}-video.mp4',
        ], check=True)
    if os.path.exists(prefix + '.m4a'):
        subprocess.run([
            'ffmpeg', '-y', '-v', 'error', *cut, '-i', prefix + '.m4a',
            '-c', 'copy', f'{out_dir}/{name}-audio.m4a',
        ], check=True)
    for kind, suffix in [('transcript', '.transcript.vtt'), ('cc', '.cc.vtt')]:
        if os.path.exists(prefix + suffix):
            trim_vtt(prefix + suffix, f'{out_dir}/{name}-{kind}.vtt', start, end)
    print('done', name, sorted(os.listdir(out_dir)), flush=True)


def main() -> None:
    date, day, *jobs = sys.argv[1:]
    for job in jobs:
        rec_id, name, start, end = job.split(':')
        trim(date, day, rec_id, name, parse_duration(start), parse_duration(end) if end else None)


if __name__ == '__main__':
    main()
