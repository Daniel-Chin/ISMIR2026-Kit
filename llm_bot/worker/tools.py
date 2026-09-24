"""Tools the agent can call. Strict JSON schemas; every result is data from
the catalogue snapshot — never instructions.

Read-only except the profile tools, which write to the caller's own
profile. User identity comes from the task payload (ctx) — the model never
sees or chooses user IDs.
"""

from typing import Any, Dict, List, Optional

from shared.catalogue import Snapshot
from worker import profiles, recommend, retrieval

MAX_ABSTRACT_CHARS = 600
ITEM_TYPE_ORDER = ("papers", "lbds", "music", "industry")


def _compact(item: Dict[str, Any], item_type: str) -> Dict[str, Any]:
    """What the model sees per item — enough to answer and to link."""
    out = {
        "item_type": item_type,
        "id": item["id"],
        "title": item["title"],
        "authors": item.get("authors", []),
        "affiliations": item.get("affiliations", []),
        "abstract": (item.get("abstract") or "")[:MAX_ABSTRACT_CHARS],
        "keywords": item.get("keywords", []),
        "miniconf_url": item.get("miniconf_url", ""),
        "slack_channel_name": item.get("slack_channel_name", ""),
        "slack_channel_id": item.get("slack_channel_id", ""),
    }
    for key in ("day", "session", "session_id", "pdf_url", "company"):
        if item.get(key) not in (None, ""):
            out[key] = item[key]
    return out


TOOL_DEFINITIONS = [
    {
        "name": "search_papers",
        "description": (
            "Hybrid keyword + semantic search over the ISMIR 2026 programme: "
            "papers, late-breaking demos (lbds), music programme, industry "
            "sessions and logistics. Call this first for any content question."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "enum": [3, 5, 8]},
                "item_type": {
                    "type": ["string", "null"],
                    "enum": ["papers", "lbds", "music", "industry", "logistics", None],
                },
            },
            "required": ["query", "k", "item_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_paper",
        "description": (
            "Fetch one item by id (works for papers, lbds, music, industry). "
            "Returns the full abstract and all links."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_schedule",
        "description": (
            "Conference schedule. Optionally filter by day number and/or "
            "session type (e.g. 'Poster session', 'Tutorials', 'Social')."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": ["integer", "null"]},
                "session_type": {"type": ["string", "null"]},
            },
            "required": ["day", "session_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_author",
        "description": "All programme items by an author (name match).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_logistics",
        "description": "Conference logistics (venue, wifi, registration, ...).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_paper",
        "description": "Save an item to the user's personal list.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "remove_saved_paper",
        "description": "Remove an item from the user's saved list.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_saved_papers",
        "description": "The user's saved items, with titles and links.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "recommend_from_saved",
        "description": (
            "Recommend papers/demos similar to the user's saved list "
            "(nearest neighbours to the saved-paper centroid, excluding "
            "saved and rejected items)."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"k": {"type": "integer", "enum": [3, 5]}},
            "required": ["k"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_feedback",
        "description": "Record the user's feedback on an item.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "feedback": {
                    "type": "string",
                    "enum": ["more_like_this", "not_relevant"],
                },
            },
            "required": ["item_id", "feedback"],
            "additionalProperties": False,
        },
    },
    {
        "name": "build_personal_schedule",
        "description": (
            "The user's personal schedule: sessions containing their saved "
            "papers, sorted by start time, with overlap conflicts flagged."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
]

PROFILE_TOOLS = {
    "save_paper",
    "remove_saved_paper",
    "list_saved_papers",
    "recommend_from_saved",
    "record_feedback",
    "build_personal_schedule",
}


def _resolve_type(snapshot: Snapshot, item_id: str) -> Optional[str]:
    for item_type in ITEM_TYPE_ORDER:
        if snapshot.get_item(item_type, item_id) is not None:
            return item_type
    return None


def _run_profile_tool(
    snapshot: Snapshot, name: str, args: Dict[str, Any], ctx: Dict[str, Any]
) -> Any:
    store, user_id = ctx["profiles"], ctx["user_id"]

    if name in ("save_paper", "remove_saved_paper", "record_feedback"):
        item_type = _resolve_type(snapshot, args["item_id"])
        if item_type is None:
            return {"error": "no item with id {}".format(args["item_id"])}
        if name == "save_paper":
            changed = profiles.save_paper(store, user_id, item_type, args["item_id"])
            return {"saved": changed, "already_saved": not changed}
        if name == "remove_saved_paper":
            changed = profiles.remove_saved_paper(
                store, user_id, item_type, args["item_id"]
            )
            return {"removed": changed}
        profiles.record_feedback(
            store, user_id, item_type, args["item_id"], args["feedback"]
        )
        return {"recorded": True}

    if name == "list_saved_papers":
        saved = profiles.list_saved(store, user_id)
        return [
            _compact(snapshot.get_item(key["item_type"], key["id"]), key["item_type"])
            for key in saved
            if snapshot.get_item(key["item_type"], key["id"]) is not None
        ]

    if name == "recommend_from_saved":
        items = recommend.from_saved(
            snapshot, store.get(user_id), k=args.get("k") or 5
        )
        if not items:
            return {"error": "no saved papers yet — save some first"}
        return [_compact(item, item["item_type"]) for item in items]

    if name == "build_personal_schedule":
        return recommend.personal_schedule(snapshot, store.get(user_id))

    return {"error": "unknown profile tool {}".format(name)}


def run_tool(
    snapshot: Snapshot,
    name: str,
    args: Dict[str, Any],
    ctx: Optional[Dict[str, Any]] = None,
) -> Any:
    if name in PROFILE_TOOLS:
        if not ctx:
            return {"error": "profile tools unavailable in this context"}
        return _run_profile_tool(snapshot, name, args, ctx)
    if name == "search_papers":
        items = retrieval.hybrid_search(
            snapshot,
            args["query"],
            k=args.get("k") or 8,
            item_type=args.get("item_type"),
        )
        return [_compact(item, item["item_type"]) for item in items]

    if name == "get_paper":
        for item_type in ITEM_TYPE_ORDER:
            item = snapshot.get_item(item_type, args["item_id"])
            if item is not None:
                full = _compact(item, item_type)
                full["abstract"] = item.get("abstract", "")  # untruncated
                return full
        return {"error": "no item with id {}".format(args["item_id"])}

    if name == "get_schedule":
        sessions = snapshot.data.get("sessions", [])
        day = args.get("day")
        session_type = (args.get("session_type") or "").lower()
        out = [
            {
                k: s[k]
                for k in (
                    "id",
                    "title",
                    "type",
                    "day",
                    "start_utc",
                    "end_utc",
                    "location",
                    "paper_ids",
                )
            }
            for s in sessions
            if (day is None or s["day"] == day)
            and (not session_type or session_type in s["type"].lower())
        ]
        return out or {"error": "no sessions matched"}

    if name == "get_author":
        needle = args["name"].strip().lower()
        matches: List[Dict[str, Any]] = []
        for item_type in ITEM_TYPE_ORDER:
            for item in snapshot.data.get(item_type, []):
                if any(needle in a.lower() for a in item.get("authors", [])):
                    matches.append(_compact(item, item_type))
        return matches or {"error": "no items by author {!r}".format(args["name"])}

    if name == "get_logistics":
        logistics = snapshot.data.get("logistics", [])
        if not logistics:
            return {"error": "no logistics information available yet"}
        needle = args["topic"].strip().lower()
        hits = [
            entry
            for entry in logistics
            if needle in entry["title"].lower() or needle in entry["body"].lower()
        ]
        return hits or logistics  # small list: return all as fallback

    return {"error": "unknown tool {}".format(name)}
