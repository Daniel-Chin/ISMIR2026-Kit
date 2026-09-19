"""Hot-swap: the store picks up a new version after the refresh window."""

import json
import sqlite3

import numpy as np

from shared import catalogue as cat_mod
from shared.catalogue import CatalogueStore, LocalSource
from tests.conftest import CATALOGUE


def write_artifacts(directory, version):
    data = dict(CATALOGUE, version=version)
    (directory / "catalogue-{}.json".format(version)).write_text(
        json.dumps(data), encoding="utf-8"
    )
    np.save(str(directory / "embeddings-{}.npy".format(version)), np.zeros((1, 4)))
    (directory / "embeddings-{}.ids.json".format(version)).write_text(
        json.dumps([{"item_type": "papers", "id": "4"}]), encoding="utf-8"
    )
    db = sqlite3.connect(str(directory / "search-{}.sqlite".format(version)))
    db.execute(
        "CREATE VIRTUAL TABLE items USING fts5("
        "item_type, item_id UNINDEXED, title, authors, abstract, keywords)"
    )
    db.commit()
    db.close()


def test_local_store_hot_swaps(tmp_path, monkeypatch):
    write_artifacts(tmp_path, "2026-01-01")
    store = CatalogueStore(source=LocalSource(str(tmp_path)))
    assert store.get().version == "2026-01-01"

    write_artifacts(tmp_path, "2026-01-02")
    # inside the refresh window: still the old version
    assert store.get().version == "2026-01-01"

    monkeypatch.setattr(cat_mod, "REFRESH_SECONDS", 0)
    assert store.get().version == "2026-01-02"


def test_refresh_failure_keeps_current(tmp_path, monkeypatch):
    write_artifacts(tmp_path, "v1")
    source = LocalSource(str(tmp_path))
    store = CatalogueStore(source=source)
    assert store.get().version == "v1"

    monkeypatch.setattr(cat_mod, "REFRESH_SECONDS", 0)
    monkeypatch.setattr(
        source, "latest_version", lambda: (_ for _ in ()).throw(IOError("gcs down"))
    )
    assert store.get().version == "v1"  # keeps serving the old snapshot
