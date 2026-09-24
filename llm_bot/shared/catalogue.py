"""Catalogue loading + 15-minute hot-swap.

The worker downloads latest.json at boot, then the versioned artifacts
(catalogue JSON, embeddings, FTS sqlite). Every request checks staleness
lazily; past 15 min it re-reads latest.json and atomically swaps in the
new snapshot when the version changed — no redeploy needed for data fixes.

Local dev: CATALOGUE_DIR=/path/to/dir skips GCS entirely and loads
whatever single version lives there (works with the mock pipeline).
"""

import glob
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from shared.config import settings

log = logging.getLogger("catalogue")

REFRESH_SECONDS = 15 * 60
ITEM_TYPES = ("papers", "lbds", "music", "industry", "logistics")


@dataclass
class Snapshot:
    version: str
    data: Dict[str, Any]
    embeddings: np.ndarray
    ids: List[Dict[str, str]]  # row -> {"item_type", "id"}
    sqlite_path: str
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)
    row_of: Dict[Tuple[str, str], int] = field(default_factory=dict)

    def __post_init__(self):
        for item_type in ITEM_TYPES:
            for item in self.data.get(item_type, []):
                self.by_key[(item_type, item["id"])] = item
        for row, ref in enumerate(self.ids):
            self.row_of[(ref["item_type"], ref["id"])] = row

    def get_item(self, item_type: str, item_id: str) -> Optional[Dict[str, Any]]:
        return self.by_key.get((item_type, item_id))

    def connect(self) -> sqlite3.Connection:
        # read-only, per-query connections: cheap and thread-safe
        return sqlite3.connect(
            "file:{}?mode=ro".format(self.sqlite_path), uri=True
        )


def _artifact_names(version: str) -> Dict[str, str]:
    return {
        "catalogue": "catalogue-{}.json".format(version),
        "embeddings": "embeddings-{}.npy".format(version),
        "ids": "embeddings-{}.ids.json".format(version),
        "sqlite": "search-{}.sqlite".format(version),
    }


def _load_from_dir(directory: str, version: str) -> Snapshot:
    names = _artifact_names(version)
    with open(os.path.join(directory, names["catalogue"]), encoding="utf-8") as f:
        data = json.load(f)
    with open(os.path.join(directory, names["ids"]), encoding="utf-8") as f:
        ids = json.load(f)
    embeddings = np.load(os.path.join(directory, names["embeddings"]))
    return Snapshot(
        version=version,
        data=data,
        embeddings=embeddings,
        ids=ids,
        sqlite_path=os.path.join(directory, names["sqlite"]),
    )


class LocalSource:
    """CATALOGUE_DIR: single version on disk, discovered from the filename."""

    def __init__(self, directory: str):
        self.directory = directory

    def latest_version(self) -> str:
        matches = sorted(glob.glob(os.path.join(self.directory, "catalogue-*.json")))
        if not matches:
            raise FileNotFoundError(
                "no catalogue-*.json in CATALOGUE_DIR={}".format(self.directory)
            )
        return re.match(
            r"catalogue-(.+)\.json", os.path.basename(matches[-1])
        ).group(1)

    def fetch(self, version: str) -> Snapshot:
        return _load_from_dir(self.directory, version)


class GCSSource:
    def __init__(self, bucket: str):
        from google.cloud import storage  # lazy: not needed locally

        bucket = bucket.replace("gs://", "").strip("/")
        self.bucket_name, _, self.prefix = bucket.partition("/")
        self.client = storage.Client()
        self.cache_dir = tempfile.mkdtemp(prefix="catalogue-")

    def _blob(self, name: str):
        path = "{}/{}".format(self.prefix, name) if self.prefix else name
        return self.client.bucket(self.bucket_name).blob(path)

    def latest_version(self) -> str:
        return json.loads(self._blob("latest.json").download_as_text())["version"]

    def fetch(self, version: str) -> Snapshot:
        for name in _artifact_names(version).values():
            target = os.path.join(self.cache_dir, name)
            if not os.path.exists(target):
                self._blob(name).download_to_filename(target)
        return _load_from_dir(self.cache_dir, version)


class CatalogueStore:
    """Thread-safe holder with lazy refresh."""

    def __init__(self, source=None):
        if source is None:
            source = (
                LocalSource(settings.catalogue_dir)
                if settings.catalogue_dir
                else GCSSource(settings.catalogue_bucket)
            )
        self.source = source
        self._lock = threading.Lock()
        self._snapshot: Optional[Snapshot] = None
        self._last_check = 0.0

    def get(self) -> Snapshot:
        now = time.time()
        if self._snapshot is not None and now - self._last_check < REFRESH_SECONDS:
            return self._snapshot
        with self._lock:
            if self._snapshot is not None and now - self._last_check < REFRESH_SECONDS:
                return self._snapshot
            try:
                version = self.source.latest_version()
                if self._snapshot is None or version != self._snapshot.version:
                    log.info("loading catalogue version %s", version)
                    self._snapshot = self.source.fetch(version)
            except Exception:
                if self._snapshot is None:
                    raise
                log.exception("catalogue refresh failed — keeping current version")
            self._last_check = now
            return self._snapshot
