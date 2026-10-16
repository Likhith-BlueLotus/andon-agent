"""Publish the agent-visible serving store to GCS (ADR-021).

    uv run python -m simulator.publish --scenarios data/scenarios
    uv run python -m simulator.publish --scenarios data/scenarios --ids R002,S001
    uv run python -m simulator.publish --scenarios data/scenarios --ids R --dry-run

Uploads, per scenario, ONLY the allow-listed files in :data:`simulator.blobstore.SCENARIO_OBJECTS`
to ``gs://<bucket>/store/v1/{scenario_id}/``, the shared tables to ``store/v1/_shared/`` and
``store/v1/manifest.json`` last (readers never see a manifest that points at missing objects).

Truth never leaves the laptop / eval bucket: ``truth.json``, ``sim_meta.json``,
``audio_truth.json`` and anything named like a label are hard-denied; JSON keys and Parquet
column names are checked against the ground-truth field names; the manifest carries ids, the
set (synthetic / real_signal), a display source label, sha256 and bytes, and nothing else.

Idempotent: an object whose sha256 (kept in GCS metadata) is unchanged is skipped; the manifest is
rewritten only when its content changes. ``--ids`` merges into the existing manifest.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from agents.schemas import CauseClass
from simulator import plant
from simulator.blobstore import (
    MANIFEST_NAME,
    MANIFEST_SCHEMA,
    SCENARIO_ID_RE,
    SCENARIO_OBJECTS,
    SHARED_DIR,
    SHARED_OBJECTS,
    STORE_PREFIX,
    GcsBucket,
    ObjectStore,
    object_name,
    sha256_hex,
)
from simulator.truth_schema import GroundTruth

DEFAULT_BUCKET = "andon-511816-assets"

# Hard deny: never uploaded, whatever the allow-list says.
DENY_NAMES = frozenset({"truth.json", "sim_meta.json", "audio_truth.json"})
DENY_PATTERN = re.compile(r"truth|label|sim_meta|eval", re.IGNORECASE)

# Ground-truth field names that are not also ordinary agent-visible columns/keys.
_VISIBLE_TOO = {"scenario_id", "asset_id", "stop_ts", "stop_station"}
TRUTH_KEYS = frozenset(set(GroundTruth.model_fields) - _VISIBLE_TOO) | {
    "eval_only",
    "hints",
    "cause_class",
    "label",
    "labels",
    "condition",
}
CAUSE_STRINGS = frozenset(c.value for c in CauseClass)

STOP_EVENT_KEYS = frozenset({
    "scenario_id", "line_id", "stopped_station", "stop_ts", "stop_code", "stop_text", "shift",
    "product_model", "plant_utc_offset", "history_start", "history_end",
})  # fmt: skip

SOURCE_LABELS = {
    "metropt3": "MetroPT-3 compressor",
    "uci_hydraulic": "UCI hydraulic rig",
    "ims_bearings": "IMS bearings",
}
SYNTHETIC_LABEL = "Synthetic line"


class PublishError(RuntimeError):
    pass


def is_denied(name: str) -> bool:
    return name in DENY_NAMES or bool(DENY_PATTERN.search(name))


assert not any(is_denied(n) for n in (*SCENARIO_OBJECTS, *SHARED_OBJECTS)), "allow/deny overlap"


def select_files(scenario_dir: Path) -> tuple[list[Path], list[str]]:
    """(allow-listed files present, names skipped). Raises if a required file is missing."""
    present = {p.name: p for p in scenario_dir.iterdir() if p.is_file()}
    chosen = [present[n] for n in SCENARIO_OBJECTS if n in present and not is_denied(n)]
    skipped = sorted(n for n in present if n not in SCENARIO_OBJECTS or is_denied(n))
    missing = {"telemetry.parquet", "stop_event.json"} - {p.name for p in chosen}
    if missing:
        raise PublishError(f"{scenario_dir.name}: missing {sorted(missing)}")
    return chosen, skipped


def _walk_keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _walk_keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _walk_keys(v)}
    return set()


def check_content(name: str, data: bytes, scenario_id: str | None) -> None:
    """Refuse objects whose keys / columns look like ground truth."""
    if name.endswith(".json"):
        doc = json.loads(data)
        bad = _walk_keys(doc) & TRUTH_KEYS
        if bad:
            raise PublishError(f"{scenario_id}/{name}: truth-like keys {sorted(bad)}")
        if name == "stop_event.json":
            extra = set(doc) - STOP_EVENT_KEYS
            if extra:
                raise PublishError(
                    f"{scenario_id}/stop_event.json: unexpected keys {sorted(extra)}"
                )
        if scenario_id is not None and doc.get("scenario_id", scenario_id) != scenario_id:
            raise PublishError(f"{scenario_id}/{name}: scenario_id mismatch")
    elif name.endswith(".parquet"):
        cols = set(pq.read_schema(io.BytesIO(data)).names)
        bad = cols & TRUTH_KEYS
        if bad:
            raise PublishError(f"{scenario_id}/{name}: truth-like columns {sorted(bad)}")
        if scenario_id is not None and "scenario_id" in cols:
            t = pq.read_table(io.BytesIO(data), columns=["scenario_id"])
            col = t.column("scenario_id")
            if pa.types.is_dictionary(col.type):
                col = col.cast(pa.string())
            ids = {v for v in pc.unique(col).to_pylist() if v is not None}
            if ids - {scenario_id}:
                raise PublishError(f"{scenario_id}/{name}: rows of other scenarios {sorted(ids)}")
    else:
        raise PublishError(f"{name}: unsupported object type")


def _parquet_bytes(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def shared_payloads(data_dir: Path) -> dict[str, bytes]:
    hist = data_dir / "work_orders.parquet"
    if not hist.exists():
        raise PublishError(f"historical work orders missing: {hist}")
    return {
        "work_orders.parquet": hist.read_bytes(),
        "assets.parquet": _parquet_bytes(pa.Table.from_pylist(plant.assets_table())),
        "spec_limits.parquet": _parquet_bytes(pa.Table.from_pylist(plant.spec_limits())),
    }


def source_info(provenance: bytes | None) -> tuple[list[str], str]:
    """(sorted source ids, display label) from the agent-visible provenance."""
    if provenance is None:
        return ["synthetic"], SYNTHETIC_LABEL
    t = pq.read_table(io.BytesIO(provenance), columns=["tag", "source_id"]).to_pylist()
    ids = sorted({r["source_id"] for r in t if r["source_id"]})
    labels = [SOURCE_LABELS[s] for s in ids if s in SOURCE_LABELS]
    return ids, " + ".join(labels) if labels else SYNTHETIC_LABEL


def _content_type(name: str) -> str:
    return "application/json" if name.endswith(".json") else "application/vnd.apache.parquet"


def _manifest_content(manifest: dict[str, Any]) -> str:
    body = {k: v for k, v in manifest.items() if k not in ("published_at", "content_sha256")}
    return sha256_hex(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


def check_manifest(manifest: dict[str, Any]) -> None:
    text = json.dumps(manifest)
    bad = _walk_keys(manifest) & TRUTH_KEYS
    if bad:
        raise PublishError(f"manifest has truth-like keys {sorted(bad)}")
    hits = sorted(c for c in CAUSE_STRINGS if re.search(rf"\b{re.escape(c)}\b", text))
    if hits:
        raise PublishError(f"manifest mentions cause classes {hits}")


def publish(
    scenarios: Path,
    bucket: ObjectStore,
    ids: list[str] | None = None,
    prefix: str = STORE_PREFIX,
    dry_run: bool = False,
    log: Any = print,
    workers: int = 4,
) -> dict[str, Any]:
    """Publish; returns ``{"manifest", "uploaded", "skipped", "objects", "bytes", "denied"}``."""
    dirs = sorted(p for p in scenarios.iterdir() if p.is_dir() and (p / "stop_event.json").exists())
    if ids:
        wanted = set(ids)
        dirs = [d for d in dirs if d.name in wanted]
        missing = wanted - {d.name for d in dirs}
        if missing:
            raise PublishError(f"unknown scenario ids {sorted(missing)}")
    if not dirs:
        raise PublishError(f"no scenarios under {scenarios}")

    existing = bucket.list_sha256(prefix.strip("/") + "/")
    # (object name, bytes or the local file to read at upload time, sha256, size) - big
    # telemetry files are not all held in memory at once
    plan: list[tuple[str, bytes | Path, str, int]] = []
    shared = shared_payloads(scenarios.parent)
    shared_entry = {}
    for name in SHARED_OBJECTS:
        data = shared[name]
        check_content(name, data, None)
        shared_entry[name] = {"sha256": sha256_hex(data), "bytes": len(data)}
        plan.append((object_name(prefix, SHARED_DIR, name), data, sha256_hex(data), len(data)))

    entries: dict[str, Any] = {}
    denied: dict[str, list[str]] = {}
    for d in dirs:
        sid = d.name
        if not SCENARIO_ID_RE.match(sid):
            raise PublishError(f"bad scenario id {sid!r}")
        files, skipped = select_files(d)
        if skipped:
            denied[sid] = skipped
        objs: dict[str, Any] = {}
        prov = None
        for f in files:
            data = f.read_bytes()
            check_content(f.name, data, sid)
            if f.name == "provenance.parquet":
                prov = data
            sha = sha256_hex(data)
            objs[f.name] = {"sha256": sha, "bytes": len(data)}
            plan.append((object_name(prefix, sid, f.name), f, sha, len(data)))
            del data
        sources, label = source_info(prov)
        stop = json.loads((d / "stop_event.json").read_text())
        entries[sid] = {
            "set": "real_signal" if sid[0] in "RC" else "synthetic",
            "source_label": label,
            "sources": sources,
            # display fields from the agent-visible stop record (what the incident picker shows)
            "line_id": stop.get("line_id"),
            "stopped_station": stop.get("stopped_station"),
            "stop_ts": stop.get("stop_ts"),
            "objects": objs,
        }

    prev: dict[str, Any] = {}
    manifest_obj = object_name(prefix, MANIFEST_NAME)
    if manifest_obj in existing:
        prev = json.loads(bucket.read(manifest_obj))
    scen = {**prev.get("scenarios", {}), **entries} if ids else entries
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "prefix": prefix.strip("/"),
        "shared": shared_entry,
        "scenarios": dict(sorted(scen.items())),
    }
    check_manifest(manifest)
    manifest["content_sha256"] = _manifest_content(manifest)

    todo = [x for x in plan if existing.get(x[0]) != x[2]]
    total = sum(x[3] for x in plan)

    def _upload(item: tuple[str, bytes | Path, str, int]) -> None:
        name, src, sha, _ = item
        data = src.read_bytes() if isinstance(src, Path) else src
        if sha256_hex(data) != sha:
            raise PublishError(f"{name}: local file changed during publish")
        bucket.write(name, data, _content_type(name), sha)

    if todo and not dry_run:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_upload, todo))
    uploaded, skipped_n = len(todo), len(plan) - len(todo)

    if prev.get("content_sha256") == manifest["content_sha256"]:
        manifest["published_at"] = prev.get("published_at")
        log(f"manifest unchanged ({len(manifest['scenarios'])} scenarios)")
    else:
        manifest["published_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        body = json.dumps(manifest, indent=1, sort_keys=True).encode()
        check_manifest(json.loads(body))
        if not dry_run:
            bucket.write(manifest_obj, body, "application/json", sha256_hex(body))
        verb = "would be written" if dry_run else "written"
        log(f"manifest {verb} ({len(manifest['scenarios'])} scenarios)")
    stale = sorted(set(prev.get("scenarios", {})) - set(scen))
    if stale:
        log(f"note: objects of {stale} remain in the bucket but are no longer in the manifest")
    return {
        "manifest": manifest,
        "uploaded": uploaded,
        "skipped": skipped_n,
        "objects": len(plan) + 1,
        "bytes": total,
        "denied": denied,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scenarios", type=Path, default=Path("data/scenarios"))
    ap.add_argument("--ids", default="", help="comma list or one-letter prefix (S / R)")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--prefix", default=STORE_PREFIX)
    ap.add_argument("--project", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=4, help="parallel uploads (1 on a slow uplink)")
    args = ap.parse_args(argv)
    tokens = [x.strip() for x in args.ids.split(",") if x.strip()]
    ids = None
    if tokens:
        all_ids = sorted(p.name for p in args.scenarios.iterdir() if p.is_dir())
        ids = [
            s for s in all_ids if any(s == t or (len(t) == 1 and s.startswith(t)) for t in tokens)
        ]
        if not ids:
            ap.error(f"--ids {args.ids!r} matches no scenario")
    t0 = time.time()
    res = publish(
        args.scenarios,
        GcsBucket(args.bucket, args.project),
        ids,
        args.prefix,
        args.dry_run,
        workers=max(1, args.workers),
    )
    n_denied = sum(len(v) for v in res["denied"].values())
    print(
        f"{'dry run: ' if args.dry_run else ''}{len(res['manifest']['scenarios'])} scenarios in "
        f"manifest; {res['objects']} objects ({res['bytes'] / 1e6:.1f} MB): "
        f"{res['uploaded']} uploaded, {res['skipped']} unchanged; "
        f"{n_denied} local files withheld (truth/labels/other) -> gs://{args.bucket}/{args.prefix}/",
    )
    print(f"done in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
