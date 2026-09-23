"""Answer delivery: chat.update the placeholder ingress posted, with
interactive buttons on paper answers.

Web API with the bot token is the only delivery path — never response_url
(LLM_plan.md section 5).
"""

from typing import Any, Dict, List

from slack_sdk import WebClient

from shared.config import settings
from worker import grounding

_client = None


def client() -> WebClient:
    global _client
    if _client is None:
        _client = WebClient(token=settings.slack_bot_token)
    return _client


def _buttons_for(item_type: str, item_id: str) -> Dict[str, Any]:
    value = "{}:{}".format(item_type, item_id)

    def btn(action_id, label):
        return {
            "type": "button",
            "action_id": action_id,
            "text": {"type": "plain_text", "text": label},
            "value": value,
        }

    return {
        "type": "actions",
        "block_id": "guide_actions",
        "elements": [
            btn("guide_save", "Save paper"),
            btn("guide_more", "More like this"),
            btn("guide_reject", "Not relevant"),
            btn("guide_add_schedule", "Add to my schedule"),
        ],
    }


def blocks_for_answer(text: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}
    ]
    citations = grounding.extract_citations(text)
    if citations:
        # buttons act on the first (top) cited item
        blocks.append(_buttons_for(*citations[0]))
    return blocks


def deliver(channel_id: str, placeholder_ts: str, text: str) -> None:
    client().chat_update(
        channel=channel_id,
        ts=placeholder_ts,
        text=text,  # notification fallback
        blocks=blocks_for_answer(text),
    )
