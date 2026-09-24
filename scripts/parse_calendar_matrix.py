"""Convert the calendar matrix to events.csv in conference local time.

Blank date headers inherit the date to their left. Blank event cells extend the
entry above; STOP ends it at that row's start time. The last row's end time
(including literal 'tbd') closes remaining events. Only the seven schedule
fields are populated; all other events-tab fields are blank.

uv run python -m scripts.parse_calendar_matrix
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from utils.shared import load_site_config

# Full events-tab header list from docs/SPREADSHEET_FORMAT.md.
FIELDS = [
    "uid", "title", "day", "start_date", "start_time", "end_time",
    "category", "description", "organiser", "organiser_emails",
    "organiser_affiliation", "organiser_bio", "image", "web_link",
    "slack_channel", "channel_url", "live_url", "thumbnail_link",
]


def preprocess_events(events: list[dict]) -> list[dict]:
    """Split completed 90-minute paper slots before assigning categories."""
    result = []
    for event in events:
        session = re.fullmatch(r"Paper Session\s*-\s*(\d+)", event["title"], re.I)
        if session is not None and event["end_time"] != "tbd":
            start = datetime.strptime(event["start_time"], "%H:%M")
            end = datetime.strptime(event["end_time"], "%H:%M")
            if end - start == timedelta(minutes=90):
                split_time = (start + timedelta(minutes=30)).strftime("%H:%M")
                result.append(dict(event, title=f"Oral Session - {session[1]}",
                                   end_time=split_time))
                result.append(dict(event, title=f"Poster Session - {session[1]}",
                                   start_time=split_time))
                continue
        result.append(event)
    return result


def category_for_title(title: str) -> str:
    """Map titles to the vocabulary documented for the events tab."""
    normalized = " ".join(title.casefold().split())
    for fragment, category in (
        ("registration", "Registration"),
        ("tutorial", "Tutorials"),
        ("awards and closing", "Awards"),
        ("opening", "Opening"),
        ("keynote", "All Meeting"),
        ("award nominee", "Award nominee"),
        ("poster session", "Poster session"),
        ("oral session", "Oral session"),
        ("majlis", "Majlis"),
        ("special session", "Special"),
        ("lunch", "Lunch"),
        ("society meeting", "Meetup"),
        ("late-breaking", "LBD"),
        ("industry", "Industry"),
        ("wimir", "WiMIR Meetup"),
        ("unconference", "Unconference"),
        ("welcome reception", "Social"),
        ("music program", "Music"),
        ("banquet", "Social"),
    ):
        if fragment in normalized:
            return category
    guess = "Meetup"
    print(title, 'has no category mapping, using', guess)
    return guess


def parse_calendar_matrix(input_path: str | Path, year: int) -> list[dict]:
    """Return events sorted by date, start time and column, with sequential IDs."""
    with Path(input_path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows or len(rows[0]) < 2:
        raise ValueError("Calendar matrix requires a time column and date headers")
    dates = []
    current_date = None
    for column, header in enumerate(rows[0][1:], start=2):
        if header.strip():
            date_text = header.split("(", 1)[0].strip()
            current_date = datetime.strptime(f"{year} {date_text}", "%Y %b %d").date()
        if current_date is None:
            raise ValueError(f"Missing date header for column {column}")
        dates.append(current_date)
    first_date = min(dates)
    active = [None] * len(dates)
    events = []
    previous_end = None
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) > len(dates) + 1:
            raise ValueError(f"Row {row_number}: more columns than the header")
        row += [""] * (len(dates) + 1 - len(row))
        match = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2}|tbd)\s*", row[0], re.I)
        if match is None:
            raise ValueError(f"Row {row_number}: invalid time range {row[0]!r}")
        start = datetime.strptime(match[1], "%H:%M").strftime("%H:%M")
        end = match[2].lower()
        if end != "tbd":
            end = datetime.strptime(end, "%H:%M").strftime("%H:%M")
            if end <= start:
                raise ValueError(f"Row {row_number}: end time must follow start time")
        if previous_end is not None and (previous_end == "tbd" or start < previous_end):
            raise ValueError(f"Row {row_number}: overlapping or unordered time ranges")
        previous_end = end
        for column, (date, cell) in enumerate(zip(dates, row[1:])):
            title = cell.strip()
            if title:
                event_ = active[column]
                if event_ is not None:
                    event_["end_time"] = start
                    active[column] = None
                if title.upper() != "STOP":
                    event = dict.fromkeys(FIELDS, "")
                    event.update(
                        title=title, day=(date - first_date).days + 1,
                        start_date=date.isoformat(), start_time=start,
                        end_time=end,
                    )
                    events.append(event)
                    active[column] = event  # type: ignore
            event_ = active[column]
            if event_ is not None:
                event_["end_time"] = end
    events = preprocess_events(events)
    events.sort(key=lambda event: (event["start_date"], event["start_time"]))
    for uid, event in enumerate(events, start=1):
        event["uid"] = uid
        event["category"] = category_for_title(event["title"])
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "sitedata/calendar_matrix.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "sitedata/events.csv")
    parser.add_argument("--site-data", type=Path, default=ROOT / "sitedata",
                        help="Directory containing config.yml (provides the year)")
    args = parser.parse_args()
    try:
        config = load_site_config(str(args.site_data))
        match = re.match(r"\s*(\d{4})\b", str(config.get("date", "")))
        if match is None:
            raise ValueError("config.yml 'date' must begin with the conference year")
        events = parse_calendar_matrix(args.input, int(match[1]))
        with args.output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, restval="")
            writer.writeheader()
            writer.writerows(events)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(events)} events to {args.output}")


if __name__ == "__main__":
    main()
