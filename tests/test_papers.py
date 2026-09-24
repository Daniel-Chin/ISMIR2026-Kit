import csv
from unittest.mock import Mock

import pandas as pd
import pytest

from miniconf_prep import setupPapers
from modules.papers import Papers
from utils import slack


@pytest.fixture
def paper_data(tmp_path):
    (tmp_path / "config.yml").write_text(
        "timezone: UTC\ndate: 2026 Nov 8-12\nminiconf_url: https://example.org\n"
    )
    with (tmp_path / "session_assignment.csv").open("w", newline="") as handle:
        csv.writer(handle).writerows([
            ["Session Name", "First", "Second"],
            ["Session Day & Time", "Mon, 10:00 - 11:30", "Tue, 10:00 - 11:30"],
            ["", "", ""],
            ["Session Chair - Onsite", "A", "B"],
            ["Session Chair - Remote", "C", "D"],
            ["Paper-1", "002", "001"],
        ])
    pd.DataFrame([
        {"uid": "001", "title": "One", "slack_channel": "paper-one",
         "authors_and_affil": "Alice (University)"},
        {"uid": "002", "title": "Two", "slack_channel": "paper-two",
         "authors_and_affil": "Bob (University)"},
    ]).to_csv(tmp_path / "papers.csv", index=False)
    pd.DataFrame([
        {"uid": "e1", "title": "Poster Session - 1", "day": 2,
         "slack_channel": "session-one", "start_date": "2026-11-09",
         "start_time": "10:00", "end_time": "11:30"},
        {"uid": "e2", "title": "Poster Session - 2", "day": 3,
         "slack_channel": "session-two", "start_date": "2026-11-10",
         "start_time": "10:00", "end_time": "11:30"},
    ]).to_csv(tmp_path / "events.csv", index=False)
    return tmp_path


def test_descriptions_use_assignments_through_cli_dispatch(paper_data, monkeypatch):
    monkeypatch.setattr(slack, "getChannelID", {"session-one": "C1", "session-two": "C2"}.get)
    update = Mock()
    monkeypatch.setattr(slack, "updateTopicandPurpose", update)

    setupPapers(str(paper_data), paper_data / "papers.csv",
                paper_data / "events.csv", "set-desc")

    assert update.call_count == 2
    first, second = [call.args for call in update.call_args_list]
    assert first[:2] == ("paper-one", "Paper 001: One")
    assert "poster_001.html" in first[2]
    assert "Poster Session - 2: Tue, Nov 10" in first[2]
    assert "<#C2|session-two>" in first[2]
    assert "<#C1|session-one>" in second[2]


def test_channel_names_use_assignments_without_adding_legacy_columns(paper_data):
    Papers(str(paper_data), paper_data / "papers.csv", False).setupSlackChannels()

    papers = pd.read_csv(paper_data / "papers.csv", dtype={"uid": str})
    assert papers["uid"].tolist() == ["001", "002"]
    assert papers["slack_channel"].tolist() == ["p2-1-one", "p1-1-two"]
    assert not {"session", "day", "position"}.intersection(papers.columns)


def test_missing_assignment_fails_before_slack_calls(paper_data, monkeypatch):
    papers = pd.read_csv(paper_data / "papers.csv", dtype={"uid": str})
    papers.loc[1, "uid"] = "999"
    papers.to_csv(paper_data / "papers.csv", index=False)
    lookup, update = Mock(), Mock()
    monkeypatch.setattr(slack, "getChannelID", lookup)
    monkeypatch.setattr(slack, "updateTopicandPurpose", update)

    with pytest.raises(ValueError, match="missing from session_assignment.csv: 999"):
        Papers(str(paper_data), paper_data / "papers.csv", False,
               paper_data / "events.csv").setSlackChannelDescription()

    lookup.assert_not_called()
    update.assert_not_called()
