"""Cloud Run "worker": Cloud Tasks HTTP target.

Flow per LLM_plan.md section 5:
  1. idempotency check (jobs/{job_id}) + per-user concurrency lock
  2. scope gate (tiered, cheap-first) + daily spend cap
  3. retrieval + Claude agent loop (or deterministic button actions)
  4. grounding validation (inside agent.answer)
  5. chat.update the placeholder (Block Kit with paper buttons)

Auth: deploy with --no-allow-unauthenticated; Cloud Tasks calls with an
OIDC token for the queue service account — Cloud Run verifies it at the
platform layer, so the app trusts /task bodies.
"""

import logging

from flask import Flask, jsonify, request

import os

from shared import limits
from shared.config import settings
from worker import actions, agent, scope_gate, slack_out
from worker.jobs import make_job_store
from worker.profiles import make_profile_store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

flask_app = Flask(__name__)
job_store = make_job_store()
profile_store = make_profile_store()
guardrails = limits.Guardrails()

ADMIN_USER_IDS = [u for u in os.environ.get("ADMIN_USER_IDS", "").split(",") if u]

_store = None


def catalogue_snapshot():
    global _store
    if _store is None:
        from shared.catalogue import CatalogueStore

        _store = CatalogueStore()
    return _store.get()


def process(payload):
    """Dispatch: button actions and profile commands are deterministic;
    questions go scope gate -> agent loop (grounding inside agent.answer)."""
    snapshot = catalogue_snapshot()

    if payload.get("source") == "action":
        return actions.handle(payload, snapshot, profile_store)

    if payload["text"].strip().lower().rstrip(".!") == actions.DELETE_COMMAND:
        profile_store.delete(payload["user_id"])
        return "Done — your saved papers, feedback and availability are deleted."

    if guardrails.over_budget():
        _maybe_alert_admins()
        return limits.UNAVAILABLE_REPLY

    in_scope, reason = scope_gate.check(snapshot, payload["text"])
    log.info("scope gate: %s (%s)", in_scope, reason)
    if not in_scope:
        return scope_gate.OUT_OF_SCOPE_REPLY

    usage_acc = {"input_tokens": 0, "output_tokens": 0}
    text = agent.answer(
        payload, snapshot, profile_store=profile_store, usage_acc=usage_acc
    )
    spent = guardrails.add_spend(usage_acc["input_tokens"], usage_acc["output_tokens"])
    log.info(
        "usage in=%d out=%d, spend today $%.2f",
        usage_acc["input_tokens"],
        usage_acc["output_tokens"],
        spent,
    )
    _maybe_alert_admins()
    return text


def _maybe_alert_admins():
    if guardrails.should_alert_admins():
        for admin in ADMIN_USER_IDS:
            try:
                slack_out.client().chat_postMessage(
                    channel=admin,
                    text=":rotating_light: ISMIR Guide hit MAX_DAILY_SPEND_USD "
                    "(${:.0f}) — answering is paused until midnight UTC.".format(
                        settings.max_daily_spend_usd
                    ),
                )
            except Exception:
                log.exception("admin alert to %s failed", admin)

BASE_FIELDS = ("job_id", "user_id", "channel_id", "placeholder_ts")


def _required_fields(payload):
    if payload.get("source") == "action":
        return BASE_FIELDS + ("action_id", "item_key")
    return BASE_FIELDS + ("text",)


@flask_app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@flask_app.post("/task")
def task():
    payload = request.get_json(silent=True) or {}
    missing = [f for f in _required_fields(payload) if f not in payload]
    if missing:
        # Malformed task: 2xx so Cloud Tasks does NOT retry it forever
        log.error("dropping malformed task, missing %s", missing)
        return jsonify({"dropped": True, "missing": missing}), 200

    job_id = payload["job_id"]
    if not job_store.try_claim(job_id):
        log.info("duplicate delivery for job %s — skipping", job_id)
        return jsonify({"duplicate": True}), 200

    # Per-user concurrency 1 (LLM_plan.md section 9)
    if not guardrails.acquire_user(payload["user_id"]):
        slack_out.deliver(
            payload["channel_id"], payload["placeholder_ts"], limits.BUSY_REPLY
        )
        job_store.mark_done(job_id)
        return jsonify({"busy": True}), 200

    try:
        text = process(payload)
        slack_out.deliver(payload["channel_id"], payload["placeholder_ts"], text)
        job_store.mark_done(job_id)
    except Exception:
        # Release the claim and 500 -> Cloud Tasks retries with backoff
        job_store.release(job_id)
        log.exception("job %s failed", job_id)
        return jsonify({"error": "internal"}), 500
    finally:
        guardrails.release_user(payload["user_id"])

    return "", 204


if __name__ == "__main__":
    flask_app.run(port=8081)
