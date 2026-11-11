'''Move the Unconference to a Zoom meeting hosted by another user in the main
account, and write its join URL into its events.csv live_url cell.

Zoom cannot transfer a meeting between users, so a new meeting is created with
the same breakout rooms and settings ZoomCreator gives the Unconference. Idempotent: a
meeting already on the host with TOPIC is reused.

Usage (from repo root; the ZOOM_API_* creds must be the org admin app):
    python -m scripts.less_generalizable.move_unconference_zoom          # plan only
    python -m scripts.less_generalizable.move_unconference_zoom --prod   # create + write CSV
'''

import argparse

import pandas as pd

import utils.zoom as zoomUtils
from modules.zoom_creator import ZoomCreator

EVENTS_CSV = 'sitedata/events.csv'
HOST_USER = 'linliwei3916+observer1@gmail.com'
SLACK_CHANNEL = 'unconference'
TOPIC = 'Unconference at ISMIR 2026'


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--prod', action='store_true', help='create the meeting and write events.csv')
    args = parser.parse_args()

    events = pd.read_csv(EVENTS_CSV, keep_default_na=False, na_values=[''])
    rows = events[events.slack_channel == SLACK_CHANNEL]
    assert len(rows) == 1, f'expected one {SLACK_CHANNEL} event in {EVENTS_CSV}'
    index, row = next(rows.iterrows())
    startTime = f"{row['start_date']}T{row['start_time']}:00"
    duration = zoomUtils._durationMinutes(row)
    timezone = zoomUtils._load_conference_timezone(EVENTS_CSV)

    existing = {m[1]: m for m in zoomUtils.getListOfMeetings(HOST_USER)}.get(TOPIC)
    if existing:
        joinUrl = existing[2]
        print(f'(existing) {TOPIC}: {joinUrl}')
    elif not args.prod:
        print(f'[plan] create on {HOST_USER}: {TOPIC} @ {startTime} {timezone} ({duration} min)')
        joinUrl = '<new join_url>'
    else:
        passcode = input('Enter passcode (empty for none): ').strip() or None
        joinUrl = zoomUtils.createMeeting(TOPIC, startTime, duration, ZoomCreator.UNCONFERENCE_ROOMS,
                                          timezone=timezone, passcode=passcode,
                                          extraSettings=zoomUtils.UNCONFERENCE_MEETING_SETTINGS,
                                          hostUser=HOST_USER)['join_url']
        print(f'(created) {TOPIC}: {joinUrl}')

    if row['live_url'] != joinUrl:
        print(f"{'' if args.prod else '[plan] '}{row['title']}: live_url {row['live_url']} -> {joinUrl}")
        events.loc[index, 'live_url'] = joinUrl
    if args.prod:
        events.to_csv(EVENTS_CSV, index=False)


if __name__ == '__main__':
    main()
