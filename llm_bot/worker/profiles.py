"""User profiles in Firestore: profiles/{slack_user_id} (LLM_plan.md §8).

    saved_papers:    [{"item_type": "papers", "id": "4"}, ...]
    rejected_papers: [{"item_type": "papers", "id": "7"}, ...]
    feedback:        [{"item_type", "id", "type", "ts"}]
    availability:    free-text constraint string
    created_at / updated_at

"Delete my ISMIR preferences" (DM command) wipes the document. Post-
conference cleanup: delete all profiles 30 days after the event unless
opted in — run as a one-off operator script, documented in bot/README.md.
"""

import datetime
from typing import Any, Dict, List, Optional

from shared.config import settings

MAX_SAVED = 200


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _empty_profile() -> Dict[str, Any]:
    return {
        "saved_papers": [],
        "rejected_papers": [],
        "feedback": [],
        "availability": "",
        "created_at": _now(),
        "updated_at": _now(),
    }


class InMemoryProfileStore:
    """LOCAL_MODE / tests."""

    def __init__(self) -> None:
        self._profiles: Dict[str, Dict[str, Any]] = {}

    def get(self, user_id: str) -> Dict[str, Any]:
        return self._profiles.setdefault(user_id, _empty_profile())

    def put(self, user_id: str, profile: Dict[str, Any]) -> None:
        profile["updated_at"] = _now()
        self._profiles[user_id] = profile

    def delete(self, user_id: str) -> None:
        self._profiles.pop(user_id, None)


class FirestoreProfileStore:
    def __init__(self, project: str):
        from google.cloud import firestore

        self.db = firestore.Client(project=project)

    def _doc(self, user_id: str):
        return self.db.collection("profiles").document(user_id)

    def get(self, user_id: str) -> Dict[str, Any]:
        doc = self._doc(user_id).get()
        return doc.to_dict() if doc.exists else _empty_profile()

    def put(self, user_id: str, profile: Dict[str, Any]) -> None:
        profile["updated_at"] = _now()
        self._doc(user_id).set(profile)

    def delete(self, user_id: str) -> None:
        self._doc(user_id).delete()


def make_profile_store():
    if settings.local_mode:
        return InMemoryProfileStore()
    return FirestoreProfileStore(settings.gcp_project)


# --- operations shared by tools and button actions -------------------------


def _key(item_type: str, item_id: str) -> Dict[str, str]:
    return {"item_type": item_type, "id": item_id}


def save_paper(store, user_id: str, item_type: str, item_id: str) -> bool:
    profile = store.get(user_id)
    key = _key(item_type, item_id)
    if key in profile["saved_papers"] or len(profile["saved_papers"]) >= MAX_SAVED:
        return False
    profile["saved_papers"].append(key)
    store.put(user_id, profile)
    return True


def remove_saved_paper(store, user_id: str, item_type: str, item_id: str) -> bool:
    profile = store.get(user_id)
    key = _key(item_type, item_id)
    if key not in profile["saved_papers"]:
        return False
    profile["saved_papers"].remove(key)
    store.put(user_id, profile)
    return True


def list_saved(store, user_id: str) -> List[Dict[str, str]]:
    return list(store.get(user_id)["saved_papers"])


def record_feedback(
    store, user_id: str, item_type: str, item_id: str, feedback_type: str
) -> None:
    profile = store.get(user_id)
    profile["feedback"].append(
        {"item_type": item_type, "id": item_id, "type": feedback_type, "ts": _now()}
    )
    if feedback_type == "not_relevant":
        key = _key(item_type, item_id)
        if key not in profile["rejected_papers"]:
            profile["rejected_papers"].append(key)
    store.put(user_id, profile)


def set_availability(store, user_id: str, availability: Optional[str]) -> None:
    profile = store.get(user_id)
    profile["availability"] = availability or ""
    store.put(user_id, profile)
