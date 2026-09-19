"""Build search artifacts from a catalogue JSON.

Produces, next to the catalogue (versioned identically):

- search-<version>.sqlite        FTS5 over title/authors/abstract/keywords
                                 for all item types (papers, lbds, music,
                                 industry, logistics)
- embeddings-<version>.npy       one float32 row per indexed item
- embeddings-<version>.ids.json  row -> {"item_type", "id"} (ids are only
                                 unique per type)

Also writes the embedding model name back into the catalogue JSON
("embedding_model") and re-validates it.

Embeddings come from the Voyage AI API (Anthropic's recommended embedding
provider) — set VOYAGE_API_KEY. For offline/mock testing pass
--fake-embeddings for deterministic hash-seeded vectors.

    python catalogue/build_index.py --catalogue build/catalogue/catalogue-2026-07-18.json
    python catalogue/build_index.py --catalogue ... --fake-embeddings
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from catalogue.schema import validate_catalogue  # noqa: E402

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
DEFAULT_MODEL = "voyage-3.5"
FAKE_MODEL = "fake-hash-256"
FAKE_DIM = 256
BATCH = 128

INDEXED_TYPES = ("papers", "lbds", "music", "industry", "logistics")


def item_text(item_type, item):
    """Text embedded / indexed per item: title + abstract/body."""
    if item_type == "logistics":
        return "{}\n{}".format(item["title"], item["body"])
    return "{}\n{}".format(item["title"], item["abstract"])


def iter_items(catalogue):
    for item_type in INDEXED_TYPES:
        for item in catalogue.get(item_type, []):
            yield item_type, item


def fake_embed(texts):
    """Deterministic per-text vectors so the mock pipeline needs no API key."""
    rows = []
    for text in texts:
        seed = int.from_bytes(
            hashlib.sha256(text.encode("utf-8")).digest()[:8], "big"
        ) % (2**32)
        vec = np.random.RandomState(seed).standard_normal(FAKE_DIM).astype(np.float32)
        rows.append(vec / np.linalg.norm(vec))
    return np.vstack(rows)


def voyage_embed(texts, model, api_key):
    rows = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start : start + BATCH]
        resp = requests.post(
            VOYAGE_URL,
            headers={"Authorization": "Bearer {}".format(api_key)},
            json={"input": batch, "model": model, "input_type": "document"},
            timeout=120,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        rows.extend([d["embedding"] for d in data])
        print("embedded {}/{}".format(min(start + BATCH, len(texts)), len(texts)))
    arr = np.asarray(rows, dtype=np.float32)
    return arr / np.linalg.norm(arr, axis=1, keepdims=True)


def build_fts(db_path, catalogue):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE VIRTUAL TABLE items USING fts5("
        "item_type, item_id UNINDEXED, title, authors, abstract, keywords)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('version', ?)", (catalogue["version"],))
    for item_type, item in iter_items(catalogue):
        conn.execute(
            "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)",
            (
                item_type,
                item["id"],
                item["title"],
                "; ".join(item.get("authors", [])),
                item.get("abstract", item.get("body", "")),
                "; ".join(item.get("keywords", [])),
            ),
        )
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", required=True, help="catalogue-<version>.json")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--fake-embeddings",
        action="store_true",
        help="deterministic offline embeddings (mock/testing only)",
    )
    args = parser.parse_args()

    with open(args.catalogue, encoding="utf-8") as f:
        catalogue = json.load(f)
    version = catalogue["version"]
    out_dir = os.path.dirname(os.path.abspath(args.catalogue))

    ids = [
        {"item_type": item_type, "id": item["id"]}
        for item_type, item in iter_items(catalogue)
    ]
    texts = [item_text(item_type, item) for item_type, item in iter_items(catalogue)]
    if not texts:
        print("catalogue has no indexable items", file=sys.stderr)
        sys.exit(1)

    if args.fake_embeddings:
        model = FAKE_MODEL
        embeddings = fake_embed(texts)
    else:
        model = args.model
        api_key = os.environ.get("VOYAGE_API_KEY")
        if not api_key:
            print(
                "VOYAGE_API_KEY not set (use --fake-embeddings for offline runs)",
                file=sys.stderr,
            )
            sys.exit(1)
        embeddings = voyage_embed(texts, model, api_key)

    np.save(os.path.join(out_dir, "embeddings-{}.npy".format(version)), embeddings)
    with open(
        os.path.join(out_dir, "embeddings-{}.ids.json".format(version)),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(ids, f)

    db_path = os.path.join(out_dir, "search-{}.sqlite".format(version))
    build_fts(db_path, catalogue)

    # Record the embedding model in the catalogue and re-validate
    catalogue["embedding_model"] = model
    errors = validate_catalogue(catalogue)
    if errors:
        for error in errors:
            print("SCHEMA ERROR:", error, file=sys.stderr)
        sys.exit(1)
    with open(args.catalogue, "w", encoding="utf-8") as f:
        json.dump(catalogue, f, ensure_ascii=False, indent=1)

    print(
        "wrote {} items: {}, embeddings {} ({}), updated {}".format(
            len(ids), db_path, embeddings.shape, model, args.catalogue
        )
    )


if __name__ == "__main__":
    main()
