"""Recommendations and the personal schedule (LLM_plan.md §7, §8).

Pure embedding math — no LLM cost. Nearest neighbours to the saved-paper
centroid (or a single paper for "More like this"), excluding saved and
rejected items.
"""

from typing import Any, Dict, List

import numpy as np

from shared.catalogue import Snapshot

RECOMMENDABLE = ("papers", "lbds")


def _neighbours(
    snapshot: Snapshot, qvec: np.ndarray, exclude: set, k: int
) -> List[Dict[str, Any]]:
    scores = snapshot.embeddings @ qvec
    out = []
    for row in np.argsort(-scores):
        ref = snapshot.ids[int(row)]
        key = (ref["item_type"], ref["id"])
        if ref["item_type"] not in RECOMMENDABLE or key in exclude:
            continue
        item = snapshot.get_item(*key)
        if item is not None:
            out.append(dict(item, item_type=ref["item_type"]))
        if len(out) >= k:
            break
    return out


def _rows(snapshot: Snapshot, keys: List[Dict[str, str]]) -> List[int]:
    return [
        snapshot.row_of[(key["item_type"], key["id"])]
        for key in keys
        if (key["item_type"], key["id"]) in snapshot.row_of
    ]


def from_saved(
    snapshot: Snapshot, profile: Dict[str, Any], k: int = 5
) -> List[Dict[str, Any]]:
    rows = _rows(snapshot, profile["saved_papers"])
    if not rows:
        return []
    centroid = snapshot.embeddings[rows].mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm == 0:
        return []
    exclude = {
        (key["item_type"], key["id"])
        for key in profile["saved_papers"] + profile["rejected_papers"]
    }
    return _neighbours(snapshot, centroid / norm, exclude, k)


def more_like_this(
    snapshot: Snapshot, item_type: str, item_id: str, k: int = 5
) -> List[Dict[str, Any]]:
    row = snapshot.row_of.get((item_type, item_id))
    if row is None:
        return []
    return _neighbours(
        snapshot, snapshot.embeddings[row], {(item_type, item_id)}, k
    )


def personal_schedule(snapshot: Snapshot, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Saved papers -> their sessions, sorted, overlap conflicts flagged."""
    saved_ids = {
        key["id"] for key in profile["saved_papers"] if key["item_type"] == "papers"
    }
    entries = []
    for session in snapshot.data.get("sessions", []):
        mine = sorted(saved_ids.intersection(session.get("paper_ids", [])))
        if mine:
            entries.append(
                {
                    "session_id": session["id"],
                    "title": session["title"],
                    "day": session["day"],
                    "start_utc": session["start_utc"],
                    "end_utc": session["end_utc"],
                    "saved_paper_ids": mine,
                }
            )
    entries.sort(key=lambda e: (e["start_utc"], e["session_id"]))

    conflicts = []
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            if a["start_utc"] and b["start_utc"] and b["start_utc"] < a["end_utc"]:
                conflicts.append([a["session_id"], b["session_id"]])
    return {"entries": entries, "conflicts": conflicts}
