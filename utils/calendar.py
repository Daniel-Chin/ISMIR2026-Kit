"""Convert loaded events.csv rows into the website calendar's schedule format."""

from datetime import datetime, timedelta

import pytz


CALENDAR_IDS = {
    "Tutorials": "tut",
    "Opening": "open",
    "Keynote session": "key",
    "Oral session": "oral",
    "All Meeting": "all",
    "Poster session": "pos",
    "Meetup": "meet",
    "VMeetup": "vmeet",
    "WiMIR Meetup": "wimir",
    "Music": "mus",
    "Social": "social",
    "Satellite": "sat",
    "Lunch": "lunch",
    "Registration": "registration",
    "Industry": "industry",
    "LBD": "lbd",
    "Awards": "awards",
    "Performance": "performance",
}


def build_calendar(events, config):
    timezone = pytz.timezone(config["timezone"])
    schedules = []
    for event in events:
        if not event["title"].strip():
            continue
        start = datetime.strptime(
            f"{event['start_date']} {event['start_time']}", "%Y-%m-%d %H:%M"
        )
        if event["end_time"].strip().lower() == "tbd":
            end = timezone.localize(start) + timedelta(hours=2)
        else:
            end = datetime.strptime(
                f"{event['start_date']} {event['end_time']}", "%Y-%m-%d %H:%M"
            )
            if end < start:
                end += timedelta(days=1)
            end = timezone.localize(end)

        category = event["category"]
        if category in {"Poster session", "Oral session"}:
            link = f"papers.html?session={event['title'].split()[-1]}"
        else:
            link = {
                "LBD": "lbds.html",
                "Industry": "industry.html?session=Platinum",
                "Tutorials": "tutorials.html",
                "Music": "music.html",
                "Satellite": event.get("web_link", ""),
            }.get(category, "")

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
            "calendarId": CALENDAR_IDS.get(category, "other"),
            "scrollKey": "\n".join(description),
        })
    return schedules
