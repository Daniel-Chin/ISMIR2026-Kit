"""Convert loaded events.csv rows into the website calendar's schedule format."""

from datetime import datetime, timedelta

import pytz

from utils.shared import event_link


def build_calendar(events, config):
    timezone = pytz.timezone(config["timezone"])
    schedules = []
    for event in events:
        if not event["title"].strip():
            continue
        start = datetime.strptime(
            f"{event['start_date']} {event['start_time']}", "%Y-%m-%d %H:%M"
        )
        end_time_tbd = event["end_time"].strip().lower() == "tbd"
        if end_time_tbd:
            end = timezone.localize(start) + timedelta(hours=3)
        else:
            end = datetime.strptime(
                f"{event['start_date']} {event['end_time']}", "%Y-%m-%d %H:%M"
            )
            if end < start:
                end += timedelta(days=1)
            end = timezone.localize(end)

        link = event_link(event)

        description = []
        if link:
            page_url = link if link.startswith(("https://", "http://")) else (
                config["miniconf_url"].rstrip("/") + "/" + link
            )
            description.append(f"Miniconf page: {page_url}")
        if event.get("channel_url"):
            description.append(f"Slack channel: {event['channel_url']}")
        if event.get("zoom_url"):
            description.append(f"Zoom: {event['zoom_url']}")
        schedules.append({
            "title": event["title"],
            "start": timezone.localize(start).astimezone(pytz.UTC).isoformat(),
            "end": end.astimezone(pytz.UTC).isoformat(),
            "location": link,
            "link": link,
            "category": "time",
            "calendarId": event["category"].replace(" ", "_"),
            "scrollKey": "\n".join(description),
            "raw": {
                "endTimeTbd": end_time_tbd,
                "sideLane": in_side_lane(event),
                "hideAfter": SPECIAL_ONLINE_HIDE_AFTER if is_special_online(event) else None,
            },
        })
    return schedules


# The calendar stops showing the special online sessions after this moment.
SPECIAL_ONLINE_HIDE_AFTER = "2026-11-12T23:59:00+04:00"


def is_hidden_now(event):
    """Past its hide-after cutoff; the ICS build drops it (the website calendar checks client-side)."""
    return is_special_online(event) and datetime.now(pytz.UTC) > datetime.fromisoformat(SPECIAL_ONLINE_HIDE_AFTER)


def is_special_online(event):
    return event["title"].startswith("Special Online Session")


def in_side_lane(event):
    """Shown in the calendar's right-hand column: Majlis and the special online sessions."""
    return event["category"] == "Majlis" or is_special_online(event)
