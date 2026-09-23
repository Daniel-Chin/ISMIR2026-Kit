"""Tiered in-scope classification, cheap-first (LLM_plan.md section 6).

1. Deterministic checks live in ingress (length, attachments).
2. Similarity vs the whole corpus + entity hits via FTS -> proceed free.
3. Only the ambiguous middle zone pays for one Haiku-class yes/no call.

No profanity keyword filters: "which paper detects explicit lyrics" is a
legitimate MIR question. Moderate behaviour, not vocabulary.
"""

import logging
import re
from typing import Tuple

from shared.catalogue import Snapshot
from shared.config import settings
from worker import retrieval

log = logging.getLogger("scope_gate")

# Cosine thresholds for real embedding models (tuned in milestone 5 against
# the eval set; meaningless for the fake test embedder, so tests monkeypatch)
SIM_STRONG = 0.45
SIM_WEAK = 0.25

OUT_OF_SCOPE_REPLY = (
    "I can help with ISMIR 2026 papers, authors, sessions, schedules and "
    "conference logistics. I can't review code or answer unrelated questions."
)

# Words that make a question conference-shaped even with low similarity
CONFERENCE_TERMS = re.compile(
    r"\b(ismir|conference|paper|papers|poster|session|schedule|tutorial|"
    r"keynote|author|lbd|demo|workshop|wifi|venue|registration|badge|"
    r"lunch|social|concert|music)\b",
    re.IGNORECASE,
)


def _entity_hit(snapshot: Snapshot, question: str) -> bool:
    """Author names / title words / uids present in the catalogue?"""
    hits = retrieval.fts_search(snapshot, question, k=1)
    return bool(hits)


def _llm_says_in_scope(question: str) -> bool:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=settings.scope_model,
        max_tokens=8,
        system=(
            "You classify questions for a conference assistant. Answer with "
            "exactly YES if the question is about the ISMIR music-information-"
            "retrieval conference (its papers, authors, sessions, schedule, "
            "music programme, industry sessions or logistics) or about MIR "
            "research topics; otherwise exactly NO."
        ),
        messages=[{"role": "user", "content": question}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text.strip().upper().startswith("YES")


def check(snapshot: Snapshot, question: str) -> Tuple[bool, str]:
    """(in_scope, reason). Cheap paths first; one small LLM call at most."""
    if CONFERENCE_TERMS.search(question):
        return True, "conference term"

    try:
        sim = retrieval.max_similarity(snapshot, question)
    except Exception:
        log.exception("similarity check failed — passing through to the agent")
        return True, "similarity unavailable"

    if sim >= SIM_STRONG:
        return True, "similarity {:.2f}".format(sim)
    if sim >= SIM_WEAK and _entity_hit(snapshot, question):
        return True, "entity hit at similarity {:.2f}".format(sim)
    if sim < SIM_WEAK:
        return False, "similarity {:.2f}".format(sim)

    # Ambiguous zone: one Haiku-class yes/no
    try:
        verdict = _llm_says_in_scope(question)
        return verdict, "llm classifier at similarity {:.2f}".format(sim)
    except Exception:
        log.exception("scope classifier failed — failing open")
        return True, "classifier unavailable"
