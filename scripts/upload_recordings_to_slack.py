"""Upload a day's trimmed recordings to the Slack recordings channel, one event at a time.

For each event (in schedule order): post a mention of the event's channel, then upload its
video, audio, transcript and cc files one by one. Nothing runs in parallel.
Messages/files the bot already posted to the target channel are skipped, so reruns resume.

uv run --env-file real.env python -m scripts.upload_recordings_to_slack day-1 --csv-day 2 --dry-run
"""

import argparse
import csv
from pathlib import Path

RECORDINGS_ROOT = Path('/home/dan/ismir2026/recordings')
EVENTS_CSV = './sitedata/events.csv'
TARGET_CHANNEL_ID = 'C0C7ME3JWAH'  # #yesterday-on-videotape
FILE_SUFFIXES = ['video.mp4', 'audio.m4a', 'transcript.vtt', 'cc.vtt']
UPLOAD_TIMEOUT_SECONDS = 1800


def start_minutes(row: dict) -> int:
    h, m = row['start_time'].split(':')
    return int(h) * 60 + int(m)


def match_event_channel(folder: str, events: list[dict]) -> str:
    '''Slack channel of the event a recording folder belongs to.

    Folder names are slugified titles, which may differ slightly from the channel name
    (award-nominees vs award-nominees-1), so fall back to containment either way.
    '''
    channels = [e['slack_channel'].strip().lstrip('#') for e in events]
    for is_match in (
        lambda c: c == folder,
        lambda c: c in folder,
        lambda c: folder in c,
    ):
        hits = [c for c in channels if c and is_match(c)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise LookupError(f'{folder}: ambiguous channels {hits}')
    raise LookupError(f'{folder}: no matching event channel')


def already_posted(slack) -> tuple[set[str], set[str]]:
    '''(texts, file names) the bot has already posted to the target channel.'''
    bot_user_id = slack.client_bot.auth_test()['user_id']
    texts, file_names = set(), set()
    for page in slack.client_bot.conversations_history(channel=TARGET_CHANNEL_ID, limit=slack.PAGE_LIMIT):
        for m in page.get('messages') or []:
            if m.get('user') != bot_user_id and m.get('bot_id') is None:
                continue
            texts.add(m.get('text', ''))
            file_names.update(f.get('name', '') for f in m.get('files') or [])
    return texts, file_names


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('day_folder', help='e.g. day-1 (under recordings/)')
    parser.add_argument('--csv-day', required=True, help='Matching `day` value in events.csv (day-1 folder = CSV day 2).')
    parser.add_argument('--dry-run', action='store_true', help='Print the plan without posting.')
    args = parser.parse_args()

    with open(EVENTS_CSV, encoding='utf-8') as f:
        events = [r for r in csv.DictReader(f) if r['day'].strip() == args.csv_day]
    channel_order = {e['slack_channel'].strip().lstrip('#'): start_minutes(e) for e in events}

    day_dir = RECORDINGS_ROOT / args.day_folder
    sessions = []
    for folder in sorted(p for p in day_dir.iterdir() if p.is_dir()):
        channel = match_event_channel(folder.name, events)
        files = [folder / f'{folder.name}-{suffix}' for suffix in FILE_SUFFIXES]
        missing = [p for p in files if not p.exists()]
        if missing:
            raise FileNotFoundError(f'missing: {missing}')
        sessions.append((channel_order[channel], channel, files))
    sessions.sort()

    if args.dry_run:
        for _, channel, files in sessions:
            print(f'#{channel}')
            for p in files:
                print(f'  {p.name}  ({p.stat().st_size / 1e6:.0f} MB)')
        return

    from utils import slack  # Imported only here: it loads Slack tokens, which a dry run doesn't need.
    slack.configure_clients(is_mockup=False)
    slack.client_bot.timeout = UPLOAD_TIMEOUT_SECONDS
    slack.client_bot.conversations_join(channel=TARGET_CHANNEL_ID)
    posted_texts, posted_files = already_posted(slack)

    for _, channel, files in sessions:
        channel_id = slack.getChannelID(channel)
        if channel_id is None:
            raise LookupError(f'Channel {channel} does not exist in the workspace.')
        mention = f'<#{channel_id}>'
        if mention in posted_texts:
            print(f'#{channel}: mention already posted')
        else:
            print(f'#{channel}: posting mention')
            slack.client_bot.chat_postMessage(channel=TARGET_CHANNEL_ID, text=mention)
        for p in files:
            if p.name in posted_files:
                print(f'  {p.name}: already uploaded')
                continue
            print(f'  {p.name}: uploading ({p.stat().st_size / 1e6:.0f} MB)...', flush=True)
            slack.client_bot.files_upload_v2(channel=TARGET_CHANNEL_ID, file=str(p), filename=p.name, title=p.name)


if __name__ == '__main__':
    main()
