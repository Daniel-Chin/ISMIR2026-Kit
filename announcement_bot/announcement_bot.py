'''
- Posts automatically on slack #announcements when a session starts.
    - Also posts the event channel description for visibility.
- Needs to be kept running throughout the conference.
- You need to create a bot:
    - https://api.slack.com/apps?new_app=1
    - New blank app.
    - App name "Announcement Bot".
    - Bot Token Scopes:
        - channels:read channels:join chat:write channels:history groups:history mpim:history im:history
    - Install App to Workspace.
    - Copy the **Bot User OAuth Token** (`xoxb-...`).
    - Paste in `.env`:
    - "SLACK_TOKEN_ANNOUNCEMENT_BOT=xoxb-..."
    - Set a profile image.  

Example CLI:
    - `uv run python -m announcement_bot.announcement_bot --mockup --path sitedata_mock`
    - `uv run python -m announcement_bot.announcement_bot`

Details:
- Stateless. Can restart anytime during conference without reconfiguring.
- After starting the script,  
    - Pull message history. Match the last message containing `KEYWORD`, if any. Extract `channel_id` to seek the right position in the event sequence. Set cursor on the next event.  
    - Send an announcement 10 minutes before the next event starts. Increment cursor.  
    - However, if an event started >=1m ago without announcement AND the script started <=10sec ago, suspect the script had been paused and ask on CLI whether to skip this announcement.  
        - If no response in 1 minute, assume skip.  
        - `t_minus` may be negative if the event has already started.  
- Loads events.csv once at startup. If you change it during the conference, restart this script.
'''

from __future__ import annotations

import argparse
import os
import re
import select
import importlib
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from utils.shared import load_conference_timezone_name

ANNOUNCE_IN_ADVANCE = 10  # minutes
ANNOUNCEMENTS_CHANNEL = "general"
KEYWORD = "Beep Bop"
PROMPT_TIMEOUT_SECONDS = 60
BOT_TOKEN_ENV_VAR = "SLACK_TOKEN_ANNOUNCEMENT_BOT"
SCRIPT_RESTART_GRACE_SECONDS = 10
MISSED_EVENT_THRESHOLD_SECONDS = 60
HISTORY_PAGE_LIMIT = 200


@dataclass(frozen=True)
class ScheduledEvent:
    title: str
    channel_id: str
    start_at: datetime


@dataclass(frozen=True)
class AnnouncementPointer:
    channel_id: str
    posted_at: datetime


def render_announcement(
    client,
    channel_id: str, t_minus: int, is_mockup: bool = False, 
) -> str:
    msg = f"{KEYWORD}. Hello everyone! <#{channel_id}> is starting in {t_minus} minutes."
    if is_mockup:
        backstage_channel_id = find_channel_id(client, 'backstage')
        return (
            f'We are in a mockup, so **ignore me** and instead follow <#{backstage_channel_id}> instructions. '
            'If this was the real conference, I would have said: \n> '
            + msg
        )
    else:
        return msg


def get_event_channel_message(client: Any, channel_id: str) -> str:
    response = client.conversations_info(channel=channel_id)
    purpose = str(
        response.get("channel", {}).get("purpose", {}).get("value", "")
    ).strip()
    return purpose


def load_events(site_data_path: str) -> list[ScheduledEvent]:
    config_path = Path(site_data_path) / "config.yml"
    assert config_path.exists()
    timezone = ZoneInfo(load_conference_timezone_name(site_data_path))
    csv_path = Path(site_data_path) / "events.csv"
    csv_data = pd.read_csv(csv_path).fillna("")

    events: list[ScheduledEvent] = []
    for _, row in csv_data.iterrows():
        channel_url = str(row.get("channel_url", "")).strip()
        _, params = channel_url.split("?")
        kv_pairs = {k: v for k, v in (pair.split("=") for pair in params.split("&"))}
        channel_id = kv_pairs.get("channel", '').strip()
        start_date = str(row.get("start_date", "")).strip()
        start_time = str(row.get("start_time", "")).strip()
        title = str(row.get("title", "")).strip()
        if not channel_id or not start_date or not start_time or not title:
            continue

        start_at = parse_event_start_datetime(start_date, start_time, timezone)
        events.append(
            ScheduledEvent(
                title=title,
                channel_id=channel_id,
                start_at=start_at,
            )
        )

    events.sort(key=lambda event: event.start_at)
    return events


def parse_event_start_datetime(
    start_date: str, start_time: str, timezone: ZoneInfo
) -> datetime:
    event_date = date.fromisoformat(start_date)
    time_parts = start_time.split(":")
    if len(time_parts) not in {2, 3}:
        raise ValueError(
            f"Invalid time '{start_time}'. Expected H:MM, HH:MM, H:MM:SS, or HH:MM:SS."
        )

    hour = int(time_parts[0])
    minute = int(time_parts[1])
    second = int(time_parts[2]) if len(time_parts) == 3 else 0
    event_time = dtime(hour=hour, minute=minute, second=second)
    return datetime.combine(event_date, event_time, tzinfo=timezone)


def create_slack_client() -> Any:
    env_path = Path(".") / ".env"
    load_dotenv(dotenv_path=env_path)
    token = os.environ.get(BOT_TOKEN_ENV_VAR, "")
    if not token:
        raise RuntimeError(
            f"Missing {BOT_TOKEN_ENV_VAR} in environment or .env file."
        )
    slack_sdk = importlib.import_module("slack_sdk")
    return slack_sdk.WebClient(token=token)


def find_channel_id(client: Any, channel_name: str) -> str:
    next_cursor: str | None = None
    while True:
        response = client.conversations_list(
            types="public_channel",
            limit=HISTORY_PAGE_LIMIT,
            cursor=next_cursor,
        )
        for channel in response.get("channels", []):
            if channel.get("name") == channel_name:
                return str(channel["id"])
        next_cursor = response.get("response_metadata", {}).get("next_cursor") or None
        if next_cursor is None:
            break
    raise RuntimeError(f"Could not find Slack channel '{channel_name}'.")


def join_channel_if_needed(client: Any, channel_id: str) -> None:
    try:
        client.conversations_join(channel=channel_id)
    except Exception as exc:
        error_response = getattr(exc, "response", {})
        error_code = error_response.get("error", "") if hasattr(error_response, "get") else ""
        if error_code not in {"method_not_supported_for_channel_type", "already_in_channel"}:
            raise


def extract_announcement_pointer(message: dict[str, Any]) -> AnnouncementPointer | None:
    text = str(message.get("text", ""))
    if KEYWORD not in text:
        return None

    match = re.search(
        r"Hello everyone!\s+<#([A-Za-z0-9]+)(?:\|[^>]+)?>\s+is starting in\s+-?\d+\s+minutes\.",
        text,
    )
    if match is None:
        return None

    ts_text = str(message.get("ts", "")).strip()
    if not ts_text:
        return None

    return AnnouncementPointer(
        channel_id=match.group(1).strip(),
        posted_at=datetime.fromtimestamp(float(ts_text), tz=ZoneInfo("UTC")),
    )


def fetch_last_announcement(
    client: Any, channel_id: str
) -> AnnouncementPointer | None:
    next_cursor: str | None = None
    while True:
        response = client.conversations_history(
            channel=channel_id,
            limit=HISTORY_PAGE_LIMIT,
            cursor=next_cursor,
        )
        for message in response.get("messages", []):
            pointer = extract_announcement_pointer(message)
            if pointer is not None:
                return pointer
        next_cursor = response.get("response_metadata", {}).get("next_cursor") or None
        if next_cursor is None:
            return None


def find_resume_index(
    events: list[ScheduledEvent],
    last_announcement: AnnouncementPointer | None,
) -> int:
    if last_announcement is None:
        return 0

    matching_positions = [
        position
        for position, event in enumerate(events)
        if event.channel_id == last_announcement.channel_id
    ]
    if not matching_positions:
        return 0

    posted_at = last_announcement.posted_at.astimezone(events[0].start_at.tzinfo)
    best_position = min(
        matching_positions,
        key=lambda position: abs(
            (
                events[position].start_at - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
                - posted_at
            ).total_seconds()
        ),
    )
    return best_position + 1


def minutes_until(event: ScheduledEvent, now: datetime) -> int:
    return round((event.start_at - now).total_seconds() / 60)


def should_prompt_for_missed_announcement(
    event: ScheduledEvent,
    now: datetime,
    started_at_monotonic: float,
) -> bool:
    return (
        (time.monotonic() - started_at_monotonic) <= SCRIPT_RESTART_GRACE_SECONDS
        and (now - event.start_at).total_seconds() >= MISSED_EVENT_THRESHOLD_SECONDS
    )


def prompt_should_skip(event: ScheduledEvent, now: datetime) -> bool:
    t_minus = minutes_until(event, now)
    print(
        f"Missed announcement for {event.title} "
        f"with t_minus={t_minus}. Skip it? [Y/n] ",
        end="",
        flush=True,
    )
    ready, _, _ = select.select([sys.stdin], [], [], PROMPT_TIMEOUT_SECONDS)
    if not ready:
        print("\nNo response received; skipping announcement.")
        return True

    answer = sys.stdin.readline().strip().lower()
    return answer not in {"n", "no"}


def sleep_until_due(event: ScheduledEvent, now: datetime) -> None:
    due_at = event.start_at - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
    seconds_until_due = max(0.0, (due_at - now).total_seconds())
    time.sleep(min(seconds_until_due, 30.0))


def post_event_channel_message(client: Any, event: ScheduledEvent) -> None:
    desc = get_event_channel_message(client, event.channel_id)
    if not desc:
        print(f"No purpose text configured for {event.title}; skipping event-channel post.")
        return

    join_channel_if_needed(client, event.channel_id)
    message = desc.lstrip('_\n')
    client.chat_postMessage(channel=event.channel_id, text=message)
    print(f"Posted event channel purpose for {event.title} to <#{event.channel_id}>.")


def post_announcement(
    client: Any,
    announcements_channel_id: str,
    event: ScheduledEvent,
    now: datetime,
    is_mockup: bool,
) -> None:
    t_minus = minutes_until(event, now)
    message = render_announcement(client, event.channel_id, t_minus, is_mockup=is_mockup)
    client.chat_postMessage(channel=announcements_channel_id, text=message)
    post_event_channel_message(client, event)
    print(
        f"Posted announcement for {event.title} at "
        f"{now.isoformat()} with t_minus={t_minus}."
    )


def run(site_data_path: str, is_mockup: bool = False) -> None:
    events = load_events(site_data_path)
    if not events:
        raise RuntimeError(f"No announceable events found in {site_data_path}/events.csv.")

    client = create_slack_client()
    announcements_channel_id = find_channel_id(
        client, ANNOUNCEMENTS_CHANNEL
    )
    join_channel_if_needed(client, announcements_channel_id)

    last_announcement = fetch_last_announcement(client, announcements_channel_id)
    cursor = find_resume_index(events, last_announcement)
    started_at_monotonic = time.monotonic()

    if last_announcement is None:
        print("No previous announcement found; starting from the first event.")
    else:
        print(
            f"Resuming after channel {last_announcement.channel_id}; next event index is {cursor}."
        )

    while cursor < len(events):
        event = events[cursor]
        now = datetime.now(tz=event.start_at.tzinfo)
        due_at = event.start_at - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
        if now < due_at:
            print(
                'Next will be '
                f"{event.title} at {due_at.isoformat()} (t_minus={minutes_until(event, now)})"
            )
            print('Sleeping...')
            sleep_until_due(event, now)
            continue

        if should_prompt_for_missed_announcement(
            event, now, started_at_monotonic
        ) and prompt_should_skip(event, now):
            print(f"Skipping stale announcement for {event.channel_id}.")
            cursor += 1
            continue

        post_announcement(client, announcements_channel_id, event, now, is_mockup)
        cursor += 1

    print("No more events to announce.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="sitedata", help="Directory containing config.yml and events.csv")
    parser.add_argument(
        "--mockup",
        action="store_true",
        help="Post mockup-formatted announcements to the mock announcements channel.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(args.path, is_mockup=args.mockup)


if __name__ == "__main__":
    main()
