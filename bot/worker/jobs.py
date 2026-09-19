"""Idempotency: jobs/{job_id} claimed exactly once (Firestore create()).

Cloud Tasks delivers at-least-once; duplicate deliveries must produce one
answer. Claim on entry; release on failure so the retry can run; mark done
on success. Firestore TTL policy on `expires_at` cleans up after 24h
(configure the TTL policy once in infra/deploy_bot.sh).
"""

import datetime
from typing import Set

from shared.config import settings


class InMemoryJobStore:
    """LOCAL_MODE / tests only."""

    def __init__(self) -> None:
        self._claimed: Set[str] = set()

    def try_claim(self, job_id: str) -> bool:
        if job_id in self._claimed:
            return False
        self._claimed.add(job_id)
        return True

    def release(self, job_id: str) -> None:
        self._claimed.discard(job_id)

    def mark_done(self, job_id: str) -> None:
        pass  # stays claimed


class FirestoreJobStore:
    def __init__(self, project: str):
        from google.cloud import firestore  # lazy: not needed locally

        self._firestore = firestore
        self.db = firestore.Client(project=project)

    def _doc(self, job_id: str):
        return self.db.collection("jobs").document(job_id)

    def try_claim(self, job_id: str) -> bool:
        from google.api_core.exceptions import AlreadyExists

        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=24
        )
        try:
            self._doc(job_id).create({"status": "claimed", "expires_at": expires})
            return True
        except AlreadyExists:
            return False

    def release(self, job_id: str) -> None:
        self._doc(job_id).delete()

    def mark_done(self, job_id: str) -> None:
        self._doc(job_id).update({"status": "done"})


def make_job_store():
    if settings.local_mode:
        return InMemoryJobStore()
    return FirestoreJobStore(settings.gcp_project)
