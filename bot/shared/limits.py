"""Cost guardrails: per-user daily limit, per-user concurrency 1, daily
spend cap (LLM_plan.md sections 9-10).

Global concurrency is a Cloud Tasks queue setting, not code.
Counters live in Firestore collection "counters"; in-memory in LOCAL_MODE.
"""

import datetime
import logging
from typing import Dict

from shared.config import settings

log = logging.getLogger("limits")

LIMIT_REPLY = (
    "You've reached today's question limit ({} per day) — it resets at "
    "midnight UTC. Your saved papers and schedule still work."
)
BUSY_REPLY = "I'm still working on your previous question — one at a time!"
UNAVAILABLE_REPLY = (
    "The assistant is temporarily unavailable (daily budget reached). "
    "It will be back tomorrow."
)

# USD per million tokens; override at deploy to match the chosen models
PRICES = {
    "input_per_mtok": 3.0,  # Sonnet-class input
    "output_per_mtok": 15.0,  # Sonnet-class output
}


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")


class InMemoryCounters:
    def __init__(self) -> None:
        self._values: Dict[str, float] = {}

    def incr(self, key: str, amount: float = 1.0) -> float:
        self._values[key] = self._values.get(key, 0.0) + amount
        return self._values[key]

    def get(self, key: str) -> float:
        return self._values.get(key, 0.0)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

    def create(self, key: str) -> bool:
        """Atomic create-if-absent (used as a lock / once-flag)."""
        if key in self._values:
            return False
        self._values[key] = 1.0
        return True


class FirestoreCounters:
    def __init__(self, project: str):
        from google.cloud import firestore

        self._firestore = firestore
        self.db = firestore.Client(project=project)

    def _doc(self, key: str):
        return self.db.collection("counters").document(key)

    def incr(self, key: str, amount: float = 1.0) -> float:
        self._doc(key).set(
            {"value": self._firestore.Increment(amount)}, merge=True
        )
        return self.get(key)

    def get(self, key: str) -> float:
        doc = self._doc(key).get()
        return (doc.to_dict() or {}).get("value", 0.0) if doc.exists else 0.0

    def delete(self, key: str) -> None:
        self._doc(key).delete()

    def create(self, key: str) -> bool:
        from google.api_core.exceptions import AlreadyExists

        try:
            self._doc(key).create({"value": 1.0})
            return True
        except AlreadyExists:
            return False


def make_counters():
    if settings.local_mode:
        return InMemoryCounters()
    return FirestoreCounters(settings.gcp_project)


class Guardrails:
    def __init__(self, counters=None):
        self.counters = counters if counters is not None else make_counters()

    # -- per-user daily question limit (checked in ingress) --

    def allow_question(self, user_id: str) -> bool:
        used = self.counters.incr("usage:{}:{}".format(user_id, _today()))
        return used <= settings.per_user_daily_limit

    # -- per-user concurrency 1 (held by the worker around a job) --

    def acquire_user(self, user_id: str) -> bool:
        return self.counters.create("active:{}".format(user_id))

    def release_user(self, user_id: str) -> None:
        self.counters.delete("active:{}".format(user_id))

    # -- daily spend cap --

    def add_spend(self, input_tokens: int, output_tokens: int) -> float:
        usd = (
            input_tokens * PRICES["input_per_mtok"]
            + output_tokens * PRICES["output_per_mtok"]
        ) / 1_000_000
        return self.counters.incr("spend:{}".format(_today()), usd)

    def over_budget(self) -> bool:
        return self.counters.get("spend:{}".format(_today())) >= (
            settings.max_daily_spend_usd
        )

    def should_alert_admins(self) -> bool:
        """True exactly once per day, when the cap is first crossed."""
        return self.over_budget() and self.counters.create(
            "alerted:{}".format(_today())
        )
