'''Move Majlis-3 and Majlis-4 to one shared Zoom meeting, hosted by another user
in the main account, and write its join URL into both events.csv live_url cells.

Zoom cannot transfer a meeting between users, so a new meeting is created with
the same settings ZoomCreator uses (utils/zoom.createMeeting), spanning from the
first event's start to the last one's end. Idempotent: a meeting already on the
host with TOPIC is reused.

Usage (from repo root; the ZOOM_API_* creds must be the org admin app):
    python -m scripts.less_generalizable.move_majlis_3_4_zoom          # plan only
    python -m scripts.less_generalizable.move_majlis_3_4_zoom --prod   # create + write CSV
'''

import argparse

import pandas as pd

import utils.zoom as zoomUtils

EVENTS_CSV = 'sitedata/events.csv'
HOST_USER = 'liwei.lin+ismir2026@nyu.edu'
SLACK_CHANNELS = ('majlis-3', 'majlis-4')
TOPIC = 'Majlis 3 and 4 at ISMIR 2026'


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--prod', action='store_true', help='create the meeting and write events.csv')
    args = parser.parse_args()

    events = pd.read_csv(EVENTS_CSV, keep_default_na=False, na_values=[''])
    rows = events[events.slack_channel.isin(SLACK_CHANNELS)]
    assert len(rows) == len(SLACK_CHANNELS), f'expected {SLACK_CHANNELS} in {EVENTS_CSV}'
    assert rows.start_date.nunique() == 1, 'events must share a date'
    span = {'start_time': min(rows.start_time), 'end_time': max(rows.end_time)}
    startTime = f"{rows.start_date.iloc[0]}T{span['start_time']}:00"
    duration = zoomUtils._durationMinutes(span)
    timezone = zoomUtils._load_conference_timezone(EVENTS_CSV)

    existing = {m[1]: m for m in zoomUtils.getListOfMeetings(HOST_USER)}.get(TOPIC)
    if existing:
        joinUrl = existing[2]
        print(f'(existing) {TOPIC}: {joinUrl}')
    elif not args.prod:
        print(f'[plan] create on {HOST_USER}: {TOPIC} @ {startTime} {timezone} ({duration} min)')
        joinUrl = '<new join_url>'
    else:
        passcode = input('Enter shared passcode (empty for none): ').strip() or None
        joinUrl = zoomUtils.createMeeting(TOPIC, startTime, duration, timezone=timezone,
                                          passcode=passcode, hostUser=HOST_USER)['join_url']
        print(f'(created) {TOPIC}: {joinUrl}')

    for index, row in rows.iterrows():
        if row['live_url'] != joinUrl:
            print(f"{'' if args.prod else '[plan] '}{row['title']}: live_url {row['live_url']} -> {joinUrl}")
            events.loc[index, 'live_url'] = joinUrl
    if args.prod:
        events.to_csv(EVENTS_CSV, index=False)


if __name__ == '__main__':
    main()
