"""Object-store layout of the live serving store (ADR-021) and a minimal bucket interface.

``simulator.publish`` writes, ``agents.store_cache`` reads. Layout under ``gs://<bucket>/``::

    store/v1/manifest.json                 scenario ids, set, display source label, sha256 + bytes
    store/v1/_shared/{work_orders,assets,spec_limits}.parquet
    store/v1/{scenario_id}/{telemetry,alarms,shift_notes,work_orders,provenance}.parquet
    store/v1/{scenario_id}/{stop_event,audio_index}.json

Only agent-visible files exist under this prefix. Ground truth and eval labels never do: the
publisher has an allow-list plus a hard deny, and the reader refuses any name outside the
allow-list (defence in depth).

Backends: :class:`GcsBucket` (google-cloud-storage, ADC) and :class:`MemoryBucket` (tests).
"""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any, Protocol

STORE_PREFIX = "store/v1"
MANIFEST_NAME = "manifest.json"
SHARED_DIR = "_shared"
MANIFEST_SCHEMA = "andon-store/v1"

# The only per-scenario files that may be published / downloaded (what simulator.load reads,
# plus the audio index the listen tool reads).
SCENARIO_OBJECTS = (
    "telemetry.parquet",
    "alarms.parquet",
    "shift_notes.parquet",
    "work_orders.parquet",
    "provenance.parquet",
    "stop_event.json",
    "audio_index.json",
)
# Shared by every scenario: historical work orders and the static plant tables.
SHARED_OBJECTS = ("work_orders.parquet", "assets.parquet", "spec_limits.parquet")

SCENARIO_ID_RE = re.compile(r"^[SRU]\d{3}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_name(prefix: str, *parts: str) -> str:
    for p in parts:
        if not p or "/" in p or p in (".", "..") or "\\" in p:
            raise ValueError(f"bad object path component {p!r}")
    return "/".join([prefix.strip("/"), *parts])


class ObjectReader(Protocol):
    def read(self, name: str) -> bytes:
        """Object bytes; raises ``FileNotFoundError`` if absent."""
        ...


class ObjectStore(ObjectReader, Protocol):
    def list_sha256(self, prefix: str) -> dict[str, str | None]:
        """``{object name: sha256 metadata or None}`` for every object under ``prefix``."""
        ...

    def write(self, name: str, data: bytes, content_type: str, sha256: str) -> None: ...


class MemoryBucket:
    """In-memory bucket for tests (thread-safe). ``reads`` counts reads per object name."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = {}  # name -> (data, type, sha256)
        self.reads: dict[str, int] = {}
        self.writes: list[str] = []
        self._lock = threading.Lock()

    def read(self, name: str) -> bytes:
        with self._lock:
            self.reads[name] = self.reads.get(name, 0) + 1
            if name not in self.objects:
                raise FileNotFoundError(name)
            return self.objects[name][0]

    def list_sha256(self, prefix: str) -> dict[str, str | None]:
        with self._lock:
            return {n: v[2] for n, v in self.objects.items() if n.startswith(prefix)}

    def write(self, name: str, data: bytes, content_type: str, sha256: str) -> None:
        with self._lock:
            self.objects[name] = (bytes(data), content_type, sha256)
            self.writes.append(name)


class GcsBucket:
    """One GCS bucket via ADC. The sha256 of each object is kept in its custom metadata so the
    publisher can skip unchanged objects with a single list call."""

    def __init__(self, bucket: str, project: str | None = None, client: Any = None) -> None:
        self.bucket_name = bucket
        self._project = project
        self._client = client
        self._lock = threading.Lock()

    def _bucket(self) -> Any:
        with self._lock:
            if self._client is None:
                from google.cloud import storage

                self._client = storage.Client(project=self._project or None)
        return self._client.bucket(self.bucket_name)

    def read(self, name: str) -> bytes:
        from google.api_core.exceptions import NotFound

        try:
            return self._bucket().blob(name).download_as_bytes(timeout=60)
        except NotFound as exc:
            raise FileNotFoundError(f"gs://{self.bucket_name}/{name}") from exc

    def list_sha256(self, prefix: str) -> dict[str, str | None]:
        b = self._bucket()
        return {
            blob.name: (blob.metadata or {}).get("sha256")
            for blob in self._client.list_blobs(b, prefix=prefix)
        }

    def write(self, name: str, data: bytes, content_type: str, sha256: str) -> None:
        blob = self._bucket().blob(name)
        blob.metadata = {"sha256": sha256}
        blob.cache_control = "no-cache" if name.endswith(MANIFEST_NAME) else "private, max-age=0"
        # chunked resumable upload: each 4 MiB chunk has its own timeout, and the write is safe
        # to retry (same name, same bytes), so a slow uplink cannot abort a whole object
        from google.cloud.storage.retry import DEFAULT_RETRY

        blob.chunk_size = 4 * 1024 * 1024
        blob.upload_from_string(data, content_type=content_type, timeout=300, retry=DEFAULT_RETRY)
