"""Citation validation before anything is posted (LLM_plan.md section 7).

The agent is instructed to link every item it discusses via its MiniConf
URL (.../poster_<id>.html etc.). We extract those ids and require:
  - every cited id exists in the catalogue
  - if retrieval returned items, the answer cites at least one

The caller retries once with corrective feedback, then falls back to
"couldn't find".
"""

import re
from typing import Any, Dict, List, Set, Tuple

from shared.catalogue import Snapshot

CITE_RE = re.compile(r"/(poster|lbd|music|industry)_([A-Za-z0-9\-]+)\.html")
URL_TYPE_TO_ITEM_TYPE = {
    "poster": "papers",
    "lbd": "lbds",
    "music": "music",
    "industry": "industry",
}


def extract_citations(text: str) -> List[Tuple[str, str]]:
    return [
        (URL_TYPE_TO_ITEM_TYPE[kind], item_id)
        for kind, item_id in CITE_RE.findall(text or "")
    ]


def validate(
    snapshot: Snapshot, answer_text: str, retrieved_keys: Set[Tuple[str, str]]
) -> List[str]:
    """Return a list of grounding problems (empty == grounded)."""
    problems = []
    citations = extract_citations(answer_text)
    for item_type, item_id in citations:
        if snapshot.get_item(item_type, item_id) is None:
            problems.append(
                "cites {}/{} which is not in the catalogue".format(item_type, item_id)
            )
    if retrieved_keys and not citations:
        problems.append(
            "discusses programme content but cites no item "
            "(every item mentioned must link its MiniConf page)"
        )
    return problems
