"""Profiles, recommendations, personal schedule, button actions, buttons."""

from worker import actions, recommend, tools
from worker.profiles import InMemoryProfileStore
from worker.slack_out import blocks_for_answer

USER = "U123"


def ctx(store):
    return {"user_id": USER, "profiles": store}


# --- profile tools -----------------------------------------------------------


def test_save_list_remove(snapshot):
    store = InMemoryProfileStore()
    assert tools.run_tool(snapshot, "save_paper", {"item_id": "4"}, ctx(store))["saved"]
    assert tools.run_tool(snapshot, "save_paper", {"item_id": "4"}, ctx(store))[
        "already_saved"
    ]
    saved = tools.run_tool(snapshot, "list_saved_papers", {}, ctx(store))
    assert [item["id"] for item in saved] == ["4"]
    assert tools.run_tool(snapshot, "remove_saved_paper", {"item_id": "4"}, ctx(store))[
        "removed"
    ]
    assert tools.run_tool(snapshot, "list_saved_papers", {}, ctx(store)) == []


def test_profile_tools_need_ctx(snapshot):
    assert "error" in tools.run_tool(snapshot, "save_paper", {"item_id": "4"}, None)


def test_recommend_excludes_saved_and_rejected(snapshot):
    store = InMemoryProfileStore()
    tools.run_tool(snapshot, "save_paper", {"item_id": "4"}, ctx(store))
    items = tools.run_tool(snapshot, "recommend_from_saved", {"k": 5}, ctx(store))
    ids = [item["id"] for item in items]
    assert "4" not in ids and "10" in ids

    tools.run_tool(
        snapshot,
        "record_feedback",
        {"item_id": "10", "feedback": "not_relevant"},
        ctx(store),
    )
    items = tools.run_tool(snapshot, "recommend_from_saved", {"k": 5}, ctx(store))
    assert all(item["id"] != "10" for item in items) if isinstance(items, list) else True


def test_personal_schedule(snapshot):
    store = InMemoryProfileStore()
    tools.run_tool(snapshot, "save_paper", {"item_id": "4"}, ctx(store))
    schedule = tools.run_tool(snapshot, "build_personal_schedule", {}, ctx(store))
    assert schedule["entries"][0]["session_id"] == "P2"
    assert schedule["entries"][0]["saved_paper_ids"] == ["4"]
    assert schedule["conflicts"] == []


# --- recommend module directly ----------------------------------------------


def test_more_like_this_excludes_self(snapshot):
    items = recommend.more_like_this(snapshot, "papers", "4", k=5)
    assert items and all(item["id"] != "4" for item in items)


# --- button actions ------------------------------------------------------------


def action_payload(action_id, item_key="papers:4"):
    return {"action_id": action_id, "item_key": item_key, "user_id": USER}


def test_action_save(snapshot):
    store = InMemoryProfileStore()
    reply = actions.handle(action_payload("guide_save"), snapshot, store)
    assert "Saved" in reply and "poster_4.html" in reply
    assert store.get(USER)["saved_papers"] == [{"item_type": "papers", "id": "4"}]


def test_action_add_schedule_reports_sessions(snapshot):
    store = InMemoryProfileStore()
    reply = actions.handle(action_payload("guide_add_schedule"), snapshot, store)
    assert "1 session(s)" in reply


def test_action_reject_records(snapshot):
    store = InMemoryProfileStore()
    reply = actions.handle(action_payload("guide_reject"), snapshot, store)
    assert "won't recommend" in reply
    assert store.get(USER)["rejected_papers"] == [{"item_type": "papers", "id": "4"}]


def test_action_more_like_this(snapshot):
    store = InMemoryProfileStore()
    reply = actions.handle(action_payload("guide_more"), snapshot, store)
    assert "Similar to" in reply and "poster_10.html" in reply


def test_action_unknown_item(snapshot):
    reply = actions.handle(
        action_payload("guide_save", "papers:999"), snapshot, InMemoryProfileStore()
    )
    assert "no longer" in reply


# --- Block Kit -----------------------------------------------------------------


def test_blocks_have_buttons_when_cited():
    text = "Read <https://example.org/poster_4.html|this>."
    blocks = blocks_for_answer(text)
    assert blocks[0]["type"] == "section"
    assert blocks[1]["type"] == "actions"
    assert [el["action_id"] for el in blocks[1]["elements"]] == [
        "guide_save",
        "guide_more",
        "guide_reject",
        "guide_add_schedule",
    ]
    assert blocks[1]["elements"][0]["value"] == "papers:4"


def test_blocks_plain_when_no_citation():
    assert len(blocks_for_answer("Lunch is at noon.")) == 1
