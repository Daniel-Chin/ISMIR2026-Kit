"""Auto-trim Zoom *local* recordings of the poster kiosks: cut the idle padding at both ends.

Usage:
  python onsite-kit/auto_trim.py <posters dir> --out DIR [--only KIOSK/SESSION ...] [--dry-run]

<posters dir> holds one folder per kiosk (a, b, ...), each with Zoom local-recording folders like
  "2026-11-10 14.45.20 Poster Session - 7/" containing videoNNN.mp4, audioNNN.m4a and maybe videoNNN.vtt.
A kiosk can have several recordings of one session (several folders, or several videoNNN.mp4 in a folder);
each is trimmed and they are joined in time order.
Outputs: <out>/poster-session-<K>/poster-session-<K>-<kiosk>.{mp4,vtt}

How it decides (audio energy is the main signal: Zoom captions often start long after people started talking):
  * a second is voiced when >= 2 of its 100 ms frames are clearly above the recording's noise floor,
    or when a caption cue starts in it;
  * a minute is active when >= --min-loud-fraction of its seconds are loud, or it has >= --min-words caption words;
  * active minutes at most --merge-gap minutes apart form a block; the block with the most active minutes is kept,
    joined with blocks of >= --min-active active minutes that follow or precede it after a lull <= --join-gap;
    it's kept from its first to its last voiced second, plus --pad. The rest (idle starts, faint hall chatter after
    the presenter left) is dropped. A recording whose best block has < --min-active active minutes is dropped.
Cuts are stream copies: the start snaps back to the previous keyframe, so a few extra seconds may be kept.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict

import numpy as np

FOLDER = re.compile(r'(\d{4}-\d\d-\d\d \d\d\.\d\d\.\d\d) Poster Session - (\d+)$')


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def frame_levels_db(m4a: str, cache_dir: str | None) -> np.ndarray:
    """Mean power (dBFS) per 100 ms."""
    cache = cache_dir and os.path.join(cache_dir, re.sub(r'\W', '_', os.path.abspath(m4a)) + '.npy')
    if cache and os.path.exists(cache):
        return np.load(cache)
    raw = subprocess.run([
        'ffmpeg', '-v', 'error', '-i', m4a, '-vn', '-ac', '1',
        '-af', 'aresample=8000,aformat=sample_fmts=flt,aeval=val(0)*val(0)', '-ar', '100', '-f', 'f32le', '-',
    ], check=True, capture_output=True).stdout
    power = np.frombuffer(raw[:len(raw) // 40 * 40], dtype='<f4').reshape(-1, 10).mean(1)
    levels = 10 * np.log10(np.maximum(1e-10, power))
    if cache:
        np.save(cache, levels)
    return levels


def vtt_timestamp_to_seconds(s: str) -> float:
    return sum(float(x) * 60 ** i for i, x in enumerate(reversed(s.strip().split(':'))))


def seconds_to_vtt_timestamp(t: float) -> str:
    return '%02d:%02d:%06.3f' % (t // 3600, t % 3600 // 60, t % 60)


def read_vtt(path: str) -> list[tuple[float, float, list[str]]]:
    if not os.path.exists(path):
        return []
    cues = []
    for block in re.split(r'\n\s*\n', open(path, encoding='utf-8').read().strip()):
        lines = block.split('\n')
        i = next((k for k, line in enumerate(lines) if '-->' in line), None)
        if i is not None:
            s, e = (vtt_timestamp_to_seconds(x.split()[0]) for x in lines[i].split('-->'))
            cues.append((s, e, lines[i + 1:]))
    return cues


def keep_range(levels: np.ndarray, cues: list, duration: float, args) -> tuple[float, float] | None:
    n_sec = int(np.ceil(duration))
    floor, high = np.percentile(levels, 10), np.percentile(levels, 98)
    threshold = max(floor + 8, floor + 0.35 * (high - floor))
    frames = np.zeros(n_sec * 10, bool)
    frames[:min(len(levels), n_sec * 10)] = (levels > threshold)[:n_sec * 10]
    loud = frames.reshape(n_sec, 10).sum(1) >= 2
    words = np.zeros(n_sec)
    for s, e, text in cues:
        words[min(int(s), n_sec - 1)] += len(' '.join(text).split())
    voiced = loud | (words > 0)

    n_min = (n_sec + 59) // 60
    pad_to = n_min * 60
    loud_m = np.pad(loud, (0, pad_to - n_sec)).reshape(n_min, 60).mean(1)
    words_m = np.pad(words, (0, pad_to - n_sec)).reshape(n_min, 60).sum(1)
    active = np.flatnonzero((loud_m >= args.min_loud_fraction) | (words_m >= args.min_words))
    if not len(active):
        return None
    blocks = np.split(active, np.flatnonzero(np.diff(active) > args.merge_gap + 1) + 1)
    best = max(blocks, key=len)
    if len(best) < args.min_active:
        return None
    first, last = best[0], best[-1]
    big = [b for b in blocks if len(b) >= args.min_active]
    for b in big:  # forward: extend over big blocks after short lulls
        if b[0] > last and b[0] - last - 1 <= args.join_gap:
            last = b[-1]
    for b in reversed(big):
        if b[-1] < first and first - b[-1] - 1 <= args.join_gap:
            first = b[0]
    v = np.flatnonzero(voiced[first * 60:(last + 1) * 60]) + first * 60
    return max(0.0, v[0] - args.pad), min(duration, v[-1] + 1 + args.pad)


def keyframe_at_or_before(video: str, t: float) -> float:
    if t <= 0:
        return 0.0
    out = run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-skip_frame', 'nokey', '-show_entries',
               'frame=pts_time', '-of', 'csv=p=0', '-read_intervals', f'{max(0, t - 120)}%{t + 0.01}', video])
    keys = [float(x) for x in out.split() if x.strip() and float(x) <= t + 1e-3]
    return max(keys) if keys else 0.0


def collect(root: str) -> dict[tuple[str, int], list[str]]:
    """(kiosk, session) -> video files in time order."""
    sessions = defaultdict(list)
    for folder in sorted(glob.glob(os.path.join(root, '*', '*'))):
        m = FOLDER.search(folder)
        if not m:
            continue
        kiosk = os.path.basename(os.path.dirname(folder))
        conf = json.load(open(os.path.join(folder, 'recording.conf')))
        listed = [item['video'] for item in conf['items']]
        # videoNNN.mp4 not in recording.conf are extra segments of the same recording (e.g. video1X, video2X).
        videos = sorted(f for f in os.listdir(folder) if re.fullmatch(r'video\d+\.mp4', f))
        for v in sorted(set(videos) | set(listed)):
            if os.path.exists(os.path.join(folder, v)):
                sessions[kiosk, int(m.group(2))].append(os.path.join(folder, v))
    return sessions


def fmt(t: float) -> str:
    return '%d:%02d:%02d' % (t // 3600, t % 3600 // 60, t % 60)


def process(kiosk: str, session: int, videos: list[str], args) -> None:
    label = f'{kiosk}/s{session}'
    pieces = []  # (video, vtt, start, end)
    for video in videos:
        audio = video.replace('/video', '/audio')[:-4] + '.m4a'
        vtt = video[:-4] + '.vtt'
        duration = float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                              audio if os.path.exists(audio) else video]))
        cues = read_vtt(vtt)
        r = keep_range(frame_levels_db(audio if os.path.exists(audio) else video, args.cache), cues, duration, args)
        name = os.path.relpath(video, args.root)
        if r is None:
            print(f'{label}: {name} ({fmt(duration)}) nothing meaningful, dropped')
            continue
        start = keyframe_at_or_before(video, r[0])
        print(f'{label}: {name} ({fmt(duration)}{", no captions" if not cues else ""})'
              f' keep {fmt(start)} - {fmt(r[1])} ({fmt(r[1] - start)})')
        pieces.append((video, vtt, start, r[1]))
    if not pieces or args.dry_run:
        return
    out_dir = os.path.join(args.out, f'poster-session-{session}')
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f'poster-session-{session}-{kiosk}')
    with tempfile.TemporaryDirectory(dir=out_dir) as tmp:
        cut_files = []
        for i, (video, _, a, b) in enumerate(pieces):
            cut = os.path.join(tmp, f'{i}.mp4')
            run(['ffmpeg', '-y', '-v', 'error', '-ss', f'{a:.3f}', '-to', f'{b:.3f}', '-i', video,
                 '-map', '0', '-c', 'copy', '-avoid_negative_ts', 'make_zero', cut])
            cut_files.append(cut)
        if len(cut_files) == 1:
            os.replace(cut_files[0], base + '.mp4.part')
        else:
            listing = os.path.join(tmp, 'list.txt')
            open(listing, 'w').write(''.join(f"file '{f}'\n" for f in cut_files))
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy',
                 '-movflags', '+faststart', '-f', 'mp4', base + '.mp4.part'])
        os.replace(base + '.mp4.part', base + '.mp4')
    out = ['WEBVTT']
    offset = 0.0
    for _, vtt, a, b in pieces:
        for s, e, text in read_vtt(vtt):
            if a < e and s < b:
                out.append(f'{seconds_to_vtt_timestamp(max(s, a) - a + offset)} --> '
                           f'{seconds_to_vtt_timestamp(min(e, b) - a + offset)}\n' + '\n'.join(text))
        offset += b - a
    if len(out) > 1:
        open(base + '.vtt', 'w', encoding='utf-8').write('\n\n'.join(out) + '\n')
    print(f'{label}: wrote {base}.mp4', flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('root', help='folder with one subfolder per kiosk')
    p.add_argument('--out', required=True)
    p.add_argument('--only', nargs='*', help='KIOSK/SESSION pairs, e.g. a/7')
    p.add_argument('--dry-run', action='store_true', help='only print what would be kept')
    p.add_argument('--cache', help='folder to cache audio energy in')
    p.add_argument('--min-loud-fraction', type=float, default=0.25, help='of the seconds of an active minute')
    p.add_argument('--min-words', type=float, default=30, help='caption words that make a minute active')
    p.add_argument('--merge-gap', type=int, default=4, help='inactive minutes tolerated inside a block')
    p.add_argument('--min-active', type=int, default=3, help='active minutes a kept block has at least')
    p.add_argument('--join-gap', type=int, default=8, help='minutes of lull across which kept blocks are joined')
    p.add_argument('--pad', type=float, default=5, help='seconds kept before the first and after the last voice')
    args = p.parse_args()
    args.root = os.path.abspath(os.path.expanduser(args.root))
    args.out = os.path.abspath(os.path.expanduser(args.out))
    if args.cache:
        os.makedirs(args.cache, exist_ok=True)
    for (kiosk, session), videos in sorted(collect(args.root).items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if not args.only or f'{kiosk}/{session}' in args.only:
            process(kiosk, session, videos, args)


if __name__ == '__main__':
    main()
