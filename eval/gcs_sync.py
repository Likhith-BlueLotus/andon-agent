"""Tiny GCS helpers for the Cloud Run eval job: pull inputs (truth, labels), resume and push results.

    python -m eval.gcs_sync pull gs://BUCKET/PREFIX LOCAL_DIR
    python -m eval.gcs_sync push LOCAL_DIR gs://BUCKET/PREFIX

``client`` is injectable so the tests need no network. Uploads are create-or-overwrite of the
named files only; nothing is ever deleted.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def split_uri(uri: str) -> tuple[str, str]:
    m = re.fullmatch(r"gs://([^/]+)/?(.*)", uri)
    if not m:
        raise ValueError(f"not a gs:// uri: {uri!r}")
    return m.group(1), m.group(2).strip("/")


def _client(client: Any) -> Any:
    if client is not None:
        return client
    from google.cloud import storage

    return storage.Client()


def pull(uri: str, dest: Path | str, client: Any = None) -> int:
    """Download every object under ``uri`` into ``dest`` (keeps relative paths). Returns the count."""
    bucket, prefix = split_uri(uri)
    dest = Path(dest)
    n = 0
    for blob in _client(client).list_blobs(bucket, prefix=prefix + "/" if prefix else ""):
        rel = blob.name[len(prefix) :].lstrip("/") if prefix else blob.name
        if not rel or rel.endswith("/") or ".." in Path(rel).parts:
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(target))
        n += 1
    return n


def push(
    local_dir: Path | str, uri: str, names: Iterable[str] | None = None, client: Any = None
) -> int:
    """Upload files of ``local_dir`` (all regular files, or just ``names``) under ``uri``."""
    bucket, prefix = split_uri(uri)
    root = Path(local_dir)
    files = (
        [root / n for n in names] if names else [p for p in sorted(root.rglob("*")) if p.is_file()]
    )
    bkt = _client(client).bucket(bucket)
    n = 0
    for p in files:
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        bkt.blob(f"{prefix}/{rel}" if prefix else rel).upload_from_filename(str(p))
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 3 or a[0] not in ("pull", "push"):
        print(__doc__)
        return 2
    if a[0] == "pull":
        print(f"pulled {pull(a[1], a[2])} objects")
    else:
        print(f"pushed {push(a[1], a[2])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
