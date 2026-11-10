"""Upload a day's trimmed recordings to the Slack recordings channel, one event at a time.

For each event (in schedule order): post a mention of the event's channel, then upload its
video, audio, transcript and cc files one by one. Nothing runs in parallel.
Messages/files the bot already posted are skipped, so reruns resume.
After an event's files are up, the event channel gets a note pointing to the recordings channel.
Sponsored events are never uploaded (no permission).

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
RELEASED_NOTICE = f'Video recordings of this event have been released in <#{TARGET_CHANNEL_ID}>.'


def start_minutes(row: dict) -> int:
    h, m = row['start_time'].split(':')
    return int(h) * 60 + int(m)


def event_channel(event: dict) -> str:
    return event['slack_channel'].strip().lstrip('#')


def match_event(folder: str, events: list[dict]) -> dict:
    '''The events.csv row a recording folder belongs to, matched via its Slack channel.

    Folder names are slugified titles, which may differ slightly from the channel name
    (award-nominees vs award-nominees-1), so fall back to containment either way.
    '''
    for is_match in (
        lambda c: c == folder,
        lambda c: c in folder,
        lambda c: folder in c,
    ):
        hits = [e for e in events if event_channel(e) and is_match(event_channel(e))]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise LookupError(f'{folder}: ambiguous channels {[event_channel(e) for e in hits]}')
    raise LookupError(f'{folder}: no matching event channel')


def already_posted(slack, channel_id: str) -> tuple[set[str], set[str]]:
    '''(texts, file names) the bot has already posted to the channel.'''
    bot_user_id = slack.client_bot.auth_test()['user_id']
    texts, file_names = set(), set()
    for page in slack.client_bot.conversations_history(channel=channel_id, limit=slack.PAGE_LIMIT):
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

    day_dir = RECORDINGS_ROOT / args.day_folder
    sessions = []
    for folder in sorted(p for p in day_dir.iterdir() if p.is_dir()):
        if folder.name.startswith('dont_upload'):
            print(f'skipping {folder.name}')
            continue
        event = match_event(folder.name, events)
        channel = event_channel(event)
        if 'sponsored' in event['title'].lower():
            print(f'WARNING: skipping {folder.name} (#{channel}): sponsored event, no permission to upload.')
            continue
        files = [folder / f'{folder.name}-{suffix}' for suffix in FILE_SUFFIXES]
        missing = [p for p in files if not p.exists()]
        if missing:
            raise FileNotFoundError(f'missing: {missing}')
        sessions.append((start_minutes(event), channel, files))
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
    posted_texts, posted_files = already_posted(slack, TARGET_CHANNEL_ID)

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
        slack.client_bot.conversations_join(channel=channel_id)
        if RELEASED_NOTICE in already_posted(slack, channel_id)[0]:
            print(f'  #{channel}: release notice already posted')
        else:
            print(f'  #{channel}: posting release notice')
            slack.client_bot.chat_postMessage(channel=channel_id, text=RELEASED_NOTICE)


if __name__ == '__main__':
    main()
