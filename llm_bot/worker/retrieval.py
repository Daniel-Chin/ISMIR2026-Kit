"""Hybrid search: FTS5 BM25 + embedding cosine, merged by reciprocal rank
fusion. Covers papers/lbds/music/industry/logistics."""

import re
from typing import Any, Dict, List, Optional

import numpy as np

from shared.catalogue import Snapshot
from shared.embeddings import embed_query

RRF_K = 60  # standard reciprocal-rank-fusion constant


def _fts_query(query: str) -> str:
    """Quote terms so user punctuation can't break FTS5 syntax; OR them so
    partial matches still rank (BM25 sorts the good ones up)."""
    terms = re.findall(r"\w+", query)
    return " OR ".join('"{}"'.format(t) for t in terms) if terms else '""'


def fts_search(
    snapshot: Snapshot, query: str, k: int, item_type: Optional[str] = None
) -> List[Dict[str, str]]:
    sql = (
        "SELECT item_type, item_id, bm25(items) AS score FROM items "
        "WHERE items MATCH ?"
    )
    params: List[Any] = [_fts_query(query)]
    if item_type:
        sql += " AND item_type = ?"
        params.append(item_type)
    sql += " ORDER BY score LIMIT ?"
    params.append(k)
    conn = snapshot.connect()
    try:
        return [
            {"item_type": row[0], "id": row[1]}
            for row in conn.execute(sql, params).fetchall()
        ]
    finally:
        conn.close()


def embedding_search(
    snapshot: Snapshot, query: str, k: int, item_type: Optional[str] = None
) -> List[Dict[str, str]]:
    if snapshot.embeddings.size == 0:
        return []
    qvec = embed_query(query, snapshot.data["embedding_model"])
    scores = snapshot.embeddings @ qvec
    order = np.argsort(-scores)
    results = []
    for row in order:
        ref = snapshot.ids[int(row)]
        if item_type and ref["item_type"] != item_type:
            continue
        results.append({"item_type": ref["item_type"], "id": ref["id"]})
        if len(results) >= k:
            break
    return results


def max_similarity(snapshot: Snapshot, query: str) -> float:
    """Best cosine similarity of the query against the whole corpus —
    used by the scope gate."""
    if snapshot.embeddings.size == 0:
        return 0.0
    qvec = embed_query(query, snapshot.data["embedding_model"])
    return float(np.max(snapshot.embeddings @ qvec))


def hybrid_search(
    snapshot: Snapshot, query: str, k: int = 8, item_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Merge both rankings with reciprocal rank fusion, return full items
    (each tagged with its item_type)."""
    fused: Dict[tuple, float] = {}
    for results in (
        fts_search(snapshot, query, k * 2, item_type),
        embedding_search(snapshot, query, k * 2, item_type),
    ):
        for rank, ref in enumerate(results):
            key = (ref["item_type"], ref["id"])
            fused[key] = fused.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)

    ranked = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
    items = []
    for (item_type_, item_id), _score in ranked:
        item = snapshot.get_item(item_type_, item_id)
        if item is not None:
            items.append(dict(item, item_type=item_type_))
    return items
