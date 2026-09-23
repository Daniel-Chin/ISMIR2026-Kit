"""Scope-gate evaluation against ~50 labeled queries (LLM_plan.md §11.5).

Run with REAL embeddings (thresholds are meaningless on the fake embedder):

    cd bot
    CATALOGUE_DIR=../build/catalogue LOCAL_MODE=1 \
        uv run python evals/run_scope_eval.py

Needs VOYAGE_API_KEY (query embeddings) and ANTHROPIC_API_KEY (the
ambiguous-zone classifier). Prints a confusion matrix and every miss —
use it to tune SIM_STRONG / SIM_WEAK in worker/scope_gate.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.catalogue import CatalogueStore  # noqa: E402
from worker import scope_gate  # noqa: E402


def main():
    queries = [
        json.loads(line)
        for line in open(
            os.path.join(os.path.dirname(__file__), "scope_queries.jsonl"),
            encoding="utf-8",
        )
        if line.strip()
    ]
    snapshot = CatalogueStore().get()

    tp = tn = fp = fn = 0
    misses = []
    for entry in queries:
        got, reason = scope_gate.check(snapshot, entry["q"])
        want = entry["in_scope"]
        if got and want:
            tp += 1
        elif not got and not want:
            tn += 1
        else:
            if got:
                fp += 1
            else:
                fn += 1
            misses.append((entry["q"], want, got, reason))

    total = len(queries)
    print("total={} accuracy={:.2f}".format(total, (tp + tn) / total))
    print("in-scope recall   {:.2f}  ({} fn)".format(tp / max(tp + fn, 1), fn))
    print("out-of-scope block {:.2f}  ({} fp let through)".format(
        tn / max(tn + fp, 1), fp
    ))
    for q, want, got, reason in misses:
        print("MISS want={} got={} [{}] {}".format(want, got, reason, q))


if __name__ == "__main__":
    main()
