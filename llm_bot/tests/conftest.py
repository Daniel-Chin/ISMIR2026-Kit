"""Shared fixture: a tiny in-memory catalogue Snapshot with real FTS5 +
fake embeddings — the same shapes catalogue/build_index.py produces."""

import os
import sqlite3

os.environ.setdefault("LOCAL_MODE", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from shared.catalogue import Snapshot  # noqa: E402
from shared.embeddings import FAKE_MODEL, _fake_embed  # noqa: E402

BASE = "https://example.org"

PAPERS = [
    {
        "id": "4",
        "title": "Reformulating Soft Dynamic Time Warping",
        "authors": ["Johannes Zeitler", "Meinard Müller"],
        "affiliations": ["AudioLabs Erlangen"],
        "abstract": "We analyze gradient artifacts in soft dynamic time warping "
        "for weakly aligned MIR training data.",
        "keywords": ["Alignment"],
        "day": 1,
        "session": 2,
        "position": 1,
        "session_id": "P2",
        "slack_channel_name": "p2-1-reformulating",
        "slack_channel_id": "C0AAA",
        "miniconf_url": BASE + "/poster_4.html",
        "pdf_url": "",
        "special_track": False,
        "award_nominee": False,
        "is_tismir": True,
    },
    {
        "id": "10",
        "title": "Histogram-Based Supervision for Automatic Music Transcription",
        "authors": ["Ada Example"],
        "affiliations": ["Example University"],
        "abstract": "Beat tracking and transcription with histogram supervision.",
        "keywords": ["Transcription"],
        "day": 2,
        "session": 3,
        "position": 5,
        "session_id": "P3",
        "slack_channel_name": "p3-5-histogram",
        "slack_channel_id": "C0BBB",
        "miniconf_url": BASE + "/poster_10.html",
        "pdf_url": "",
        "special_track": False,
        "award_nominee": False,
        "is_tismir": False,
    },
]

CATALOGUE = {
    "version": "test",
    "conference": {
        "name": "ISMIR 2026",
        "timezone": "Asia/Dubai",
        "site_base_url": BASE,
    },
    "embedding_model": FAKE_MODEL,
    "papers": PAPERS,
    "lbds": [],
    "music": [],
    "industry": [],
    "sessions": [
        {
            "id": "P2",
            "title": "Poster Session - 2",
            "type": "Poster session",
            "day": 1,
            "start_utc": "2026-07-20T05:00:00+00:00",
            "end_utc": "2026-07-20T06:30:00+00:00",
            "location": "",
            "description": "",
            "slack_channel_name": "",
            "slack_channel_id": "",
            "paper_ids": ["4"],
        }
    ],
    "logistics": [
        {"id": "wifi", "title": "WiFi", "body": "SSID ismir2026, password mir4life"}
    ],
}


@pytest.fixture()
def snapshot(tmp_path):
    db_path = str(tmp_path / "search-test.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE VIRTUAL TABLE items USING fts5("
        "item_type, item_id UNINDEXED, title, authors, abstract, keywords)"
    )
    rows, ids = [], []
    for item_type in ("papers", "lbds", "music", "industry", "logistics"):
        for item in CATALOGUE[item_type]:
            body = item.get("abstract", item.get("body", ""))
            conn.execute(
                "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)",
                (
                    item_type,
                    item["id"],
                    item["title"],
                    "; ".join(item.get("authors", [])),
                    body,
                    "; ".join(item.get("keywords", [])),
                ),
            )
            ids.append({"item_type": item_type, "id": item["id"]})
            rows.append(_fake_embed("{}\n{}".format(item["title"], body)))
    conn.commit()
    conn.close()
    return Snapshot(
        version="test",
        data=CATALOGUE,
        embeddings=np.vstack(rows),
        ids=ids,
        sqlite_path=db_path,
    )
