"""Button-click handling. Deterministic — profile writes and embedding
math only, zero LLM cost."""

from typing import Any, Dict, List

from shared.catalogue import Snapshot
from worker import profiles, recommend

DELETE_COMMAND = "delete my ismir preferences"


def _link(item: Dict[str, Any]) -> str:
    line = "<{}|{}>".format(item["miniconf_url"], item["title"])
    if item.get("slack_channel_id"):
        line += " (<#{}>)".format(item["slack_channel_id"])
    return line


def format_items(items: List[Dict[str, Any]]) -> str:
    return "\n".join("• " + _link(item) for item in items)


def handle(payload: Dict[str, Any], snapshot: Snapshot, store) -> str:
    """payload: {action_id, item_key "papers:4", user_id, ...} -> reply text."""
    action_id = payload["action_id"]
    item_type, _, item_id = payload["item_key"].partition(":")
    user_id = payload["user_id"]
    item = snapshot.get_item(item_type, item_id)
    if item is None:
        return "That item is no longer in the program catalogue."

    if action_id in ("guide_save", "guide_add_schedule"):
        added = profiles.save_paper(store, user_id, item_type, item_id)
        reply = (
            ":white_check_mark: Saved {}".format(_link(item))
            if added
            else "Already on your list: {}".format(_link(item))
        )
        if action_id == "guide_add_schedule":
            schedule = recommend.personal_schedule(snapshot, store.get(user_id))
            reply += "\nYour schedule now covers {} session(s)".format(
                len(schedule["entries"])
            )
            if schedule["conflicts"]:
                reply += " — :warning: overlaps: {}".format(
                    ", ".join(" & ".join(pair) for pair in schedule["conflicts"])
                )
            reply += ". Ask me for *my schedule* anytime."
        return reply

    if action_id == "guide_reject":
        profiles.record_feedback(store, user_id, item_type, item_id, "not_relevant")
        return "Noted — I won't recommend {} again.".format(_link(item))

    if action_id == "guide_more":
        profiles.record_feedback(store, user_id, item_type, item_id, "more_like_this")
        similar = recommend.more_like_this(snapshot, item_type, item_id, k=5)
        if not similar:
            return "I couldn't find anything similar in the program."
        return "Similar to {}:\n{}".format(_link(item), format_items(similar))

    return "Unknown action."
