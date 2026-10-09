#!/usr/bin/env python3
"""Import ISMIR programme CSV sources into data/schedule.json.

Primary source format:
  - events.csv: public event/session calendar
  - papers.csv: public paper/poster metadata

The importer is intentionally conservative:
  - It imports only public-facing event/session, paper, and asset fields.
  - It never exports review/meta-review/reviewer/score/confidence/decision fields.
  - It does not export author or organiser email fields.
  - Paper rows do not receive per-paper Zoom links. A Poster session's
    Zoom ``live_url`` values become the parent ``links.zoom`` (including Oral);
    other livestream URLs become ``links.youtube`` (Livestream).

Usage:
  python scripts/import_schedule_sources.py data/sources/events.csv data/sources/papers.csv data/schedule.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS = ROOT / "data" / "sources" / "events.csv"
DEFAULT_PAPERS = ROOT / "data" / "sources" / "papers.csv"
DEFAULT_OUTPUT = ROOT / "data" / "schedule.json"
CONFERENCE_TZ = "Asia/Dubai"
REVIEW_FIELD_HINTS = {
    "review", "reviewer", "meta_review", "metareview", "score", "confidence", "rating",
    "recommendation", "decision", "accept", "reject", "rebuttal", "conflict", "bidding",
    "rank", "chair", "area chair", "secret", "private", "internal",
}
PRIVATE_FIELD_NAMES = {
    "author_emails", "primary_email", "email", "emails", "contact_email", "contact",
    "organiser_emails", "publish_reviews", "review1", "review2", "review3", "review4",
    "meta_review", "",
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def slugify(text: Any) -> str:
    s = clean_text(text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "item"


def compact_key(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(text).lower())


def is_private_or_review_field(header: Any) -> bool:
    raw = clean_text(header).lower()
    compact = compact_key(raw)
    if raw in PRIVATE_FIELD_NAMES or compact in {compact_key(x) for x in PRIVATE_FIELD_NAMES}:
        return True
    return any(h in raw or compact_key(h) in compact for h in REVIEW_FIELD_HINTS)


def strip_miro(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_miro(v) for k, v in obj.items() if k != "miro"}
    if isinstance(obj, list):
        return [strip_miro(x) for x in obj]
    return obj


def parse_int(value: Any) -> int | None:
    s = clean_text(value)
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        m = re.search(r"\d+", s)
        return int(m.group(0)) if m else None


def normalize_presenter_mode(value: Any) -> str:
    s = clean_text(value).lower()
    if "virtual" in s or "online" in s or "remote" in s:
        return "online"
    if "hybrid" in s or "mixed" in s:
        return "mixed"
    return "onsite"


def parse_authors(authors_and_affil: Any) -> str:
    raw = clean_text(authors_and_affil)
    if not raw:
        return "Authors TBA"
    parts = []
    for part in raw.split(";"):
        part = clean_text(part)
        if not part:
            continue
        name = re.sub(r"\s*\([^)]*\)", "", part).replace("*", "").strip()
        if name:
            parts.append(name)
    return "; ".join(parts) if parts else raw


def parse_subjects(row: dict[str, Any]) -> list[str]:
    subjects: list[str] = []
    for key in ("primary_subject", "secondary_subject"):
        value = clean_text(row.get(key))
        if not value:
            continue
        for item in value.split(";"):
            item = clean_text(item)
            if item and item not in subjects:
                subjects.append(item)
    return subjects


def load_csv(path: Path, *, filter_private: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, Any]] = []
        ignored: set[str] = set()
        for raw in reader:
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if filter_private and is_private_or_review_field(key):
                    if clean_text(key):
                        ignored.add(clean_text(key))
                    continue
                row[clean_text(key)] = value
            if clean_text(row.get("title")):
                rows.append(row)
        if ignored:
            print("Ignored private/review-like columns:", ", ".join(sorted(ignored)), file=sys.stderr)
        return rows


def event_type(title: str, category: str) -> str:
    t = title.lower()
    c = category.lower()
    if "poster session" in t:
        return "poster"
    if "oral session" in t:
        return "oral"
    if "keynote" in t:
        return "keynote"
    if "tutorial" in t:
        return "tutorial"
    if "lunch" in t or "lunch" in c:
        return "lunch"
    if "coffee" in t or "break" in c:
        return "break"
    if "registration" in t or "registration" in c:
        return "registration"
    if "late-breaking" in t or "demo" in t or c in {"lbd", "demo"}:
        return "demo"
    if "industry" in t or "industry" in c:
        return "industry"
    if "wimir" in t or "community" in c:
        return "community"
    if "unconference" in t:
        return "unconference"
    if any(x in t for x in ("banquet", "reception", "party")) or c == "social":
        return "social"
    if "concert" in t or "music program" in t or c in {"music", "performance"}:
        return "performance"
    if any(x in t for x in ("opening", "closing", "award")) or c in {"opening", "awards"}:
        return "ceremony"
    if "board" in t or "society meeting" in t:
        return "meeting"
    if "special session" in t:
        return "special"
    return "session"


def topic_from_event(typ: str, category: str) -> str:
    labels = {
        "poster": "Poster presentations",
        "oral": "Oral paper session",
        "keynote": "Keynote",
        "tutorial": "Tutorial",
        "lunch": "Break",
        "break": "Break",
        "industry": "Industry",
        "community": "Community",
        "demo": "Late-breaking / demo",
        "performance": "Music / performance",
        "social": "Social event",
        "ceremony": "Conference ceremony",
        "special": "Special session",
    }
    return labels.get(typ) or clean_text(category) or "Programme"


def parse_local_datetime(date_value: Any, time_value: Any, tz_name: str = CONFERENCE_TZ) -> datetime:
    date_text = clean_text(date_value)
    time_text = clean_text(time_value)
    if not date_text or not time_text:
        raise ValueError(f"Missing event date/time: date={date_text!r}, time={time_text!r}")
    parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    parsed_time = None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_time = datetime.strptime(time_text, fmt).time()
            break
        except ValueError:
            pass
    if parsed_time is None:
        raise ValueError(f"Unsupported time format: {time_text!r}")
    return datetime.combine(parsed_date, parsed_time, tzinfo=ZoneInfo(tz_name))


def event_datetimes(row: dict[str, Any]) -> tuple[str, str]:
    start = parse_local_datetime(row.get("start_date"), row.get("start_time"))
    end = parse_local_datetime(row.get("start_date"), row.get("end_time"))
    if end <= start:
        end += timedelta(days=1)
    return start.isoformat(), end.isoformat()


def session_number_from_title(title: str) -> int | None:
    m = re.search(r"(?:Poster|Oral)\s+Session\s*-?\s*(\d+)", title, flags=re.I)
    return int(m.group(1)) if m else None


def build_paper(row: dict[str, Any], event_id: str) -> dict[str, Any]:
    session_no = parse_int(row.get("session")) or 0
    position = parse_int(row.get("position")) or 0
    uid = clean_text(row.get("uid"))
    pid = f"P{session_no}-{position:02d}" if session_no and position else f"P-{uid or slugify(row.get('title'))}"
    slack_slug = clean_text(row.get("slack_channel"))
    links: dict[str, str] = {}
    if clean_text(row.get("channel_url")):
        links["slack"] = clean_text(row.get("channel_url"))
    elif slack_slug:
        links["slack"] = slack_slug
    # Intentionally no Zoom link here. Poster Zoom belongs to the parent session.
    asset_map = {
        "pdf_path": "pdf",
        "video": "video",
        "poster_pdf": "poster",
        "slides_pdf": "slides",
        "thumbnail": "thumbnail",
    }
    for source_key, link_key in asset_map.items():
        value = clean_text(row.get(source_key))
        if value:
            links[link_key] = value
    aliases = [pid]
    if uid:
        aliases += [uid, f"uid-{uid}", f"paper-{uid}"]
    if session_no and position:
        aliases += [f"P{session_no}-{position}", f"S{session_no}-P{position}", f"session-{session_no}-position-{position}"]
    if slack_slug:
        aliases.append(slack_slug)
    paper = {
        "id": pid,
        "aliases": list(dict.fromkeys([a for a in aliases if a])),
        "sessionId": event_id,
        "sourcePaperId": uid,
        "sessionNumber": session_no,
        "posterSessionNumber": session_no,
        "sessionPaperNumber": position,
        "title": clean_text(row.get("title")),
        "authors": parse_authors(row.get("authors_and_affil")),
        "primaryAuthor": clean_text(row.get("primary_author")),
        "presenterMode": normalize_presenter_mode(row.get("paper_presentation")),
        "abstract": clean_text(row.get("abstract")),
        "funFact": clean_text(row.get("funfact") or row.get("fun_fact") or row.get("fun fact")),
        "subjects": parse_subjects(row),
        "isTismir": clean_text(row.get("is_tismir")).upper() == "TRUE",
        "longPresentation": clean_text(row.get("long_presentation")).upper() == "TRUE",
        "links": strip_miro(links),
    }
    return {k: v for k, v in paper.items() if v not in ("", [], None)}


def group_papers_by_session(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        session = parse_int(row.get("session"))
        if session is not None:
            out[session].append(row)
    for items in out.values():
        items.sort(key=lambda r: (parse_int(r.get("position")) or 9999, clean_text(r.get("title"))))
    return out


def infer_conference(event_rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [clean_text(r.get("start_date")) for r in event_rows if clean_text(r.get("start_date"))]
    starts_on = min(dates) if dates else ""
    ends_on = max(dates) if dates else ""
    return {
        "name": "ISMIR 2026",
        "location": "Abu Dhabi, UAE",
        "theme": "Crossroads",
        "timeZone": CONFERENCE_TZ,
        "startsOn": starts_on,
        "endsOn": ends_on,
        "pageTitle": "What’s going on now",
        "subtitle": "Imported from events.csv and papers.csv.",
    }


def build_schedule(events_path: Path, papers_path: Path, output_path: Path) -> dict[str, Any]:
    event_rows = load_csv(events_path, filter_private=True)
    paper_rows = load_csv(papers_path, filter_private=True)
    by_session = group_papers_by_session(paper_rows)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    for idx, row in enumerate(event_rows, start=1):
        title = clean_text(row.get("title"))
        if not title:
            continue
        uid = clean_text(row.get("uid"))
        category = clean_text(row.get("category"))
        typ = event_type(title, category)
        session_no = session_number_from_title(title)
        source_id = f"event-{uid}" if uid else slugify(title)
        event_id = source_id
        suffix = 2
        while event_id in seen:
            event_id = f"{source_id}-{suffix}"
            suffix += 1
        seen.add(event_id)
        starts_at, ends_at = event_datetimes(row)

        links: dict[str, str] = {}
        if clean_text(row.get("web_link")):
            links["info"] = clean_text(row.get("web_link"))
        if clean_text(row.get("channel_url")):
            links["slack"] = clean_text(row.get("channel_url"))
        elif clean_text(row.get("slack_channel")):
            links["slack"] = clean_text(row.get("slack_channel"))
        # live_url is session-level only and is never copied to papers.
        # Classify by URL, not session type: Oral sessions can use Zoom Webinars.
        live_url = clean_text(row.get("live_url"))
        if live_url:
            host = (urlparse(live_url).hostname or "").lower()
            if re.search(r"(^|\.)(zoom\.us|zoom\.com|zoomgov\.com)$", host):
                links["zoom"] = live_url
            else:
                links["youtube"] = live_url
        if clean_text(row.get("thumbnail_link")):
            links["thumbnail"] = clean_text(row.get("thumbnail_link"))

        aliases = [event_id]
        if uid:
            aliases += [uid, f"uid-{uid}", f"event-{uid}"]
        event: dict[str, Any] = {
            "id": event_id,
            "aliases": list(dict.fromkeys(aliases)),
            "sourceRow": idx,
            "sourceEventId": uid,
            "dayNumber": parse_int(row.get("day")),
            "day": datetime.fromisoformat(starts_at).strftime("%A"),
            "track": "poster" if typ == "poster" else "main",
            "type": typ,
            "category": category,
            "title": title,
            "topic": topic_from_event(typ, category),
            "startsAt": starts_at,
            "endsAt": ends_at,
            "spotlight": typ == "keynote",
            "links": strip_miro(links),
            "summary": clean_text(row.get("description")),
            "organiser": clean_text(row.get("organiser")),
            "organiserAffiliation": clean_text(row.get("organiser_affiliation")),
            "organiserBio": clean_text(row.get("organiser_bio")),
            "image": clean_text(row.get("image")),
        }
        if "zoom" in links:
            event["zoomKind"] = "meeting" if typ == "poster" else "webinar"
        if session_no is not None:
            event["sessionNumber"] = session_no
        if typ in {"poster", "oral"} and session_no is not None:
            if typ == "poster":
                event["posterSessionNumber"] = session_no
            papers = [build_paper(p, event_id) for p in by_session.get(session_no, [])]
            event["papers"] = papers
            if papers:
                positions = [p.get("sessionPaperNumber") for p in papers if isinstance(p.get("sessionPaperNumber"), int)]
                event["paperRange"] = {"first": min(positions), "last": max(positions)} if positions else {"first": 1, "last": len(papers)}
        events.append({k: v for k, v in event.items() if v not in ("", [], None)})

    events.sort(key=lambda e: (e.get("startsAt", ""), e.get("track", ""), e.get("id", "")))
    return {
        "schemaVersion": 7,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": [events_path.name, papers_path.name if papers_path.exists() else ""],
        "conference": infer_conference(event_rows),
        "events": events,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import events.csv and papers.csv into data/schedule.json")
    parser.add_argument("events", nargs="?", default=str(DEFAULT_EVENTS))
    parser.add_argument("papers", nargs="?", default=str(DEFAULT_PAPERS))
    parser.add_argument("output", nargs="?", default=str(DEFAULT_OUTPUT))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    events_path = Path(args.events).resolve()
    papers_path = Path(args.papers).resolve()
    output_path = Path(args.output).resolve()
    if not events_path.exists():
        print(f"Events source not found: {events_path}", file=sys.stderr)
        return 2
    if not papers_path.exists():
        print(f"Papers source not found: {papers_path}; continuing without paper metadata.", file=sys.stderr)
    schedule = build_schedule(events_path, papers_path, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schedule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    programme_events = [e for e in schedule["events"] if not e.get("debugOnly")]
    poster_papers = sum(len(e.get("papers", [])) for e in programme_events if e.get("type") == "poster")
    poster_zoom_sessions = sum(1 for e in programme_events if e.get("type") == "poster" and e.get("links", {}).get("zoom"))
    oral_livestream_sessions = sum(1 for e in programme_events if e.get("type") == "oral" and e.get("links", {}).get("youtube"))
    paper_zoom_links = sum(1 for e in programme_events if e.get("type") == "poster" for p in e.get("papers", []) if p.get("links", {}).get("zoom"))
    print(f"Wrote {output_path}")
    print(f"Programme events: {len(programme_events)}")
    print(f"Poster papers: {poster_papers}")
    print(f"Poster sessions with session Zoom: {poster_zoom_sessions}")
    print(f"Oral sessions with Livestream: {oral_livestream_sessions}")
    print(f"Poster papers with Zoom links: {paper_zoom_links}")
    print("Review/private fields: ignored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
