"""Query embeddings, matching whatever model built the index.

The catalogue records its embedding model; queries MUST use the same one.
"fake-hash-256" mirrors catalogue/build_index.py's offline embedder so the
whole assistant runs end-to-end against mock artifacts with no API key.
"""

import hashlib
import os

import numpy as np
import requests

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
FAKE_MODEL = "fake-hash-256"
FAKE_DIM = 256


def _fake_embed(text: str) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big") % (
        2**32
    )
    vec = np.random.RandomState(seed).standard_normal(FAKE_DIM).astype(np.float32)
    return vec / np.linalg.norm(vec)


def embed_query(text: str, model: str) -> np.ndarray:
    if model == FAKE_MODEL:
        return _fake_embed(text)
    resp = requests.post(
        VOYAGE_URL,
        headers={"Authorization": "Bearer {}".format(os.environ["VOYAGE_API_KEY"])},
        json={"input": [text], "model": model, "input_type": "query"},
        timeout=30,
    )
    resp.raise_for_status()
    vec = np.asarray(resp.json()["data"][0]["embedding"], dtype=np.float32)
    return vec / np.linalg.norm(vec)
