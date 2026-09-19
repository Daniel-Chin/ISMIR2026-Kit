"""Retrieval, tools, grounding and scope-gate tests on the fixture snapshot."""

from worker import grounding, retrieval, scope_gate, tools


# --- retrieval --------------------------------------------------------------


def test_fts_finds_paper_by_keyword(snapshot):
    hits = retrieval.fts_search(snapshot, "dynamic time warping", k=3)
    assert {"item_type": "papers", "id": "4"} in hits


def test_fts_survives_punctuation(snapshot):
    # quotes/operators in user text must not crash FTS5
    assert retrieval.fts_search(snapshot, 'what is "NEAR(" AND?', k=3) is not None


def test_embedding_search_exact_text_is_top(snapshot):
    # fake embedder is deterministic: identical text -> identical vector
    query = "Reformulating Soft Dynamic Time Warping\nWe analyze gradient " \
        "artifacts in soft dynamic time warping for weakly aligned MIR " \
        "training data."
    hits = retrieval.embedding_search(snapshot, query, k=1)
    assert hits[0] == {"item_type": "papers", "id": "4"}
    assert retrieval.max_similarity(snapshot, query) > 0.99


def test_hybrid_returns_full_items(snapshot):
    items = retrieval.hybrid_search(snapshot, "beat tracking transcription", k=3)
    assert any(item["id"] == "10" for item in items)
    assert all("miniconf_url" in item for item in items if item["item_type"] == "papers")


# --- tools ------------------------------------------------------------------


def test_get_paper(snapshot):
    item = tools.run_tool(snapshot, "get_paper", {"item_id": "4"})
    assert item["title"].startswith("Reformulating")
    assert item["slack_channel_id"] == "C0AAA"
    assert tools.run_tool(snapshot, "get_paper", {"item_id": "nope"})["error"]


def test_get_schedule_filters(snapshot):
    sessions = tools.run_tool(
        snapshot, "get_schedule", {"day": 1, "session_type": "poster"}
    )
    assert sessions[0]["id"] == "P2" and sessions[0]["paper_ids"] == ["4"]
    assert "error" in tools.run_tool(
        snapshot, "get_schedule", {"day": 9, "session_type": None}
    )


def test_get_author(snapshot):
    items = tools.run_tool(snapshot, "get_author", {"name": "müller"})
    assert items[0]["id"] == "4"


def test_get_logistics(snapshot):
    hits = tools.run_tool(snapshot, "get_logistics", {"topic": "wifi"})
    assert hits[0]["id"] == "wifi"


def test_search_papers_tool(snapshot):
    items = tools.run_tool(
        snapshot, "search_papers", {"query": "transcription", "k": 3, "item_type": None}
    )
    assert any(i["id"] == "10" for i in items)


# --- grounding ----------------------------------------------------------------


def test_grounding_extracts_slack_style_links(snapshot):
    text = "Try <https://example.org/poster_4.html|this paper> in <#C0AAA>."
    assert grounding.extract_citations(text) == [("papers", "4")]
    assert grounding.validate(snapshot, text, {("papers", "4")}) == []


def test_grounding_rejects_unknown_id(snapshot):
    text = "See <https://example.org/poster_999.html|fake>."
    problems = grounding.validate(snapshot, text, {("papers", "4")})
    assert any("999" in p for p in problems)


def test_grounding_requires_citation_when_retrieved(snapshot):
    problems = grounding.validate(snapshot, "Great paper, trust me.", {("papers", "4")})
    assert problems


def test_grounding_ok_without_retrieval(snapshot):
    # e.g. "when is lunch" answered from schedule tool returning dicts only
    assert grounding.validate(snapshot, "Lunch is at 12:00 GST.", set()) == []


# --- scope gate ---------------------------------------------------------------


def test_scope_conference_term_short_circuits(snapshot):
    ok, reason = scope_gate.check(snapshot, "when is the poster session?")
    assert ok and reason == "conference term"


def test_scope_rejects_low_similarity(snapshot, monkeypatch):
    monkeypatch.setattr(scope_gate.retrieval, "max_similarity", lambda s, q: 0.05)
    ok, _ = scope_gate.check(snapshot, "write me a sorting algorithm in rust")
    assert not ok


def test_scope_strong_similarity_passes(snapshot, monkeypatch):
    monkeypatch.setattr(scope_gate.retrieval, "max_similarity", lambda s, q: 0.9)
    ok, _ = scope_gate.check(snapshot, "gradient artifacts weak alignment")
    assert ok
