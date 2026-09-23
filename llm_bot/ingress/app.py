"""Cloud Run "ingress": verify Slack signature, ack < 3s, enqueue, done.

Three entry points, one backend (LLM_plan.md section 4):
  1. DM with the app (Messages tab)      -> message event in an IM channel
  2. @ISMIR Guide mention in a channel   -> app_mention event
  3. /ask-ismir <question>               -> slash command (one-shot fallback)

Rules (section 5): signature + timestamp freshness (Bolt), deterministic
pre-checks, post a "Searching…" placeholder, enqueue a Cloud Task keyed by
the Slack event_id, and NOTHING else — the queue does the heavy work.
"""

import logging
import re

from flask import Flask, jsonify, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

from shared import limits
from shared.config import settings
from shared.tasks import make_queue

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ingress")

PLACEHOLDER = ":mag: Searching the ISMIR 2026 programme…"
TOO_LONG = (
    "That question is too long — please keep it under {} characters.".format(
        settings.max_input_chars
    )
)
NO_FILES = "I can only read text for now — please ask without attachments."

bolt = App(
    # dummy fallbacks keep the module importable in tests / LOCAL_MODE
    token=settings.slack_bot_token or "xoxb-local-dev",
    signing_secret=settings.slack_signing_secret or "local-dev",
    token_verification_enabled=bool(settings.slack_bot_token),
    # verify signature + reject stale timestamps is Bolt default behaviour
)
queue = make_queue()
guardrails = limits.Guardrails()


def _precheck(text: str, has_files: bool):
    """Deterministic rejects that must not cost a task or an LLM call."""
    if has_files:
        return NO_FILES
    if len(text) > settings.max_input_chars:
        return TOO_LONG
    if not text.strip():
        return "Ask me about ISMIR 2026 papers, authors, sessions or logistics!"
    return None


def _over_daily_limit(user_id: str) -> bool:
    """Per-user daily question limit — counted here so rejected questions
    never cost a task or an LLM call. Button clicks don't count."""
    return not guardrails.allow_question(user_id)


LIMIT_TEXT = limits.LIMIT_REPLY.format(settings.per_user_daily_limit)


def _dispatch(client, *, job_id, user_id, channel_id, thread_ts, text, source):
    """Post the placeholder, then enqueue. Runs inside the 3s ack window —
    both calls are fast; the worker does everything slow."""
    placeholder = client.chat_postMessage(
        channel=channel_id, thread_ts=thread_ts, text=PLACEHOLDER
    )
    queue.enqueue(
        {
            "job_id": job_id,
            "user_id": user_id,
            "channel_id": placeholder["channel"],
            "thread_ts": thread_ts,
            "placeholder_ts": placeholder["ts"],
            "text": text,
            "source": source,
        }
    )


@bolt.event("message")
def on_dm(body, event, client, ack):
    ack()
    # Only direct messages; ignore bot echoes and edits
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
        return
    text = event.get("text", "")
    reject = _precheck(text, bool(event.get("files")))
    thread_ts = event.get("thread_ts") or event.get("ts")
    if not reject and _over_daily_limit(event["user"]):
        reject = LIMIT_TEXT
    if reject:
        client.chat_postMessage(
            channel=event["channel"], thread_ts=thread_ts, text=reject
        )
        return
    _dispatch(
        client,
        job_id=body.get("event_id"),
        user_id=event["user"],
        channel_id=event["channel"],
        thread_ts=thread_ts,
        text=text,
        source="dm",
    )


@bolt.event("app_mention")
def on_mention(body, event, client, ack):
    ack()
    text = event.get("text", "")
    reject = _precheck(text, bool(event.get("files")))
    thread_ts = event.get("thread_ts") or event.get("ts")
    if not reject and _over_daily_limit(event["user"]):
        reject = LIMIT_TEXT
    if reject:
        client.chat_postMessage(
            channel=event["channel"], thread_ts=thread_ts, text=reject
        )
        return
    _dispatch(
        client,
        job_id=body.get("event_id"),
        user_id=event["user"],
        channel_id=event["channel"],
        thread_ts=thread_ts,
        text=text,
        source="mention",
    )


@bolt.action(re.compile("^guide_"))
def on_button(ack, body, action, client):
    """Buttons on paper answers -> same ingress -> queue path as questions."""
    ack()
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")
    placeholder = client.chat_postMessage(
        channel=channel_id, thread_ts=thread_ts, text=PLACEHOLDER
    )
    queue.enqueue(
        {
            # action_ts is unique per click — safe idempotency key
            "job_id": "action-{}".format(action.get("action_ts", body.get("trigger_id"))),
            "user_id": body["user"]["id"],
            "channel_id": placeholder["channel"],
            "thread_ts": thread_ts,
            "placeholder_ts": placeholder["ts"],
            "action_id": action["action_id"],
            "item_key": action["value"],
            "source": "action",
        }
    )


@bolt.command("/ask-ismir")
def on_slash(ack, command, client):
    text = command.get("text", "")
    reject = _precheck(text, False)
    if not reject and _over_daily_limit(command["user_id"]):
        reject = LIMIT_TEXT
    if reject:
        ack(reject)  # ephemeral, zero cost
        return
    ack("On it — answer coming up in this channel.")
    # Slash commands are not retried by Slack: trigger_id is a fine job key
    _dispatch(
        client,
        job_id="slash-{}".format(command["trigger_id"]),
        user_id=command["user_id"],
        channel_id=command["channel_id"],
        thread_ts=None,
        text=text,
        source="slash",
    )


flask_app = Flask(__name__)
handler = SlackRequestHandler(bolt)


@flask_app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


if __name__ == "__main__":
    flask_app.run(port=8080)
