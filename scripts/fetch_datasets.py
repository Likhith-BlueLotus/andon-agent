"""Fetch the public datasets on the docs/DATA_SOURCES.md USE list into data/raw/.

Usage (MIMII + IMS need the ``fetch`` extra for ``remotezip``)::

    uv run --extra fetch python scripts/fetch_datasets.py \
        --only metropt3,uci_hydraulic,ims_bearings,mimii,maintie

What it does, per dataset:
1. Re-checks the licence on a machine-readable page (regex must match) and records the date.
   A mismatch stops that dataset; nothing is downloaded for it.
2. Downloads with streaming, resume (HTTP Range) and retries. Huge archives are never pulled
   whole: MIMII wavs and the single IMS test set are range-extracted with ``remotezip``.
3. Writes ``<raw>/<id>/manifest.json`` (url, licence, check date, files with SHA-256 + bytes,
   transforms, citation). Reruns skip any file whose SHA-256 already matches the manifest.
4. Re-renders ``data/SOURCES.md`` from every manifest on disk (that file is committed; the raw
   data is not).

Only fetch-time transforms (unzip, range-extract, unrar) are recorded here; scenario-level
mapping transforms are recorded per segment in each scenario's ``provenance.parquet``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import requests

LOG = logging.getLogger("fetch_datasets")
REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
USER_AGENT = "andon-agent-fetch/1.0 (+https://github.com/; research/hackathon use)"
CHUNK = 1 << 20  # 1 MiB
CONNECT_TIMEOUT_S = 20
READ_TIMEOUT_S = 120
MAX_RETRIES = 6
MIN_RATE_BPS = 64 * 1024  # reconnect if a connection stays below this ...
RATE_WINDOW_S = 60.0  # ... averaged over this window
MAX_SLOW_RESTARTS = 3
EXTRACTED_SUMMARY_THRESHOLD = 50  # SOURCES.md lists extracted files individually below this

# --------------------------------------------------------------------------------------
# Pure helpers (unit-tested offline)
# --------------------------------------------------------------------------------------


def sha256_file(path: Path, chunk_size: int = CHUNK) -> str:
    """Streaming SHA-256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk_size):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FileRecord:
    """One file on disk under ``<raw>/<id>/``."""

    path: str  # POSIX path relative to the dataset dir
    sha256: str
    bytes: int
    source: str  # URL, or "<zip url>::<member>" for range-extracted members
    role: str = "file"  # file | archive | extracted

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "source": self.source,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FileRecord:
        return cls(
            path=d["path"],
            sha256=d["sha256"],
            bytes=int(d["bytes"]),
            source=d.get("source", ""),
            role=d.get("role", "file"),
        )


def build_manifest(
    *,
    spec: DatasetSpec,
    licence_check: dict[str, Any],
    downloaded_date: str,
    files: Iterable[FileRecord],
    transforms: Iterable[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files_sorted = sorted(files, key=lambda f: f.path)
    return {
        "manifest_version": MANIFEST_VERSION,
        "id": spec.id,
        "name": spec.name,
        "url": spec.page_url,
        "download_urls": list(spec.download_urls),
        "licence": spec.licence,
        "licence_check": licence_check,
        "downloaded_date": downloaded_date,
        "citation": spec.citation,
        "maps_to": spec.maps_to,
        "redistribution_note": spec.redistribution_note,
        "files": [f.to_dict() for f in files_sorted],
        "total_bytes": sum(f.bytes for f in files_sorted),
        "transforms": list(transforms),
        "extra": extra or {},
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOG.warning("corrupt manifest ignored: %s", path)
        return None


def manifest_index(manifest: dict[str, Any] | None) -> dict[str, FileRecord]:
    """path -> FileRecord from a (possibly missing) manifest."""
    if not manifest:
        return {}
    return {d["path"]: FileRecord.from_dict(d) for d in manifest.get("files", [])}


def is_up_to_date(path: Path, expected: FileRecord | None) -> bool:
    """True when ``path`` exists and matches the recorded size and SHA-256."""
    if expected is None or not path.is_file():
        return False
    if path.stat().st_size != expected.bytes:
        return False
    return sha256_file(path) == expected.sha256


def check_licence_text(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def select_balanced(names: Iterable[str], n: int, seed: str) -> list[str]:
    """Deterministically pick ``n`` names spread evenly over groups.

    ``names`` look like ``pump/id_00/normal/00000012.wav``; the group is the parent directory.
    Each group gets ``n // k`` picks (the first ``n % k`` groups in sorted order get one more),
    capped at the group size. Selection inside a group is a seeded shuffle of the sorted names,
    so it is stable across runs, platforms and listing order.
    """
    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(str(PurePosixPath(name).parent), []).append(name)
    if not groups or n <= 0:
        return []
    keys = sorted(groups)
    base, rem = divmod(n, len(keys))
    picked: list[str] = []
    for i, key in enumerate(keys):
        want = base + (1 if i < rem else 0)
        members = sorted(groups[key])
        rng = random.Random(f"{seed}|{key}")
        rng.shuffle(members)
        picked.extend(sorted(members[:want]))
    return sorted(picked)


def safe_member_target(dest_dir: Path, member: str, strip_prefix: str = "") -> Path:
    """Map an archive member to a path inside ``dest_dir``; refuse traversal."""
    rel = (
        member[len(strip_prefix) :] if strip_prefix and member.startswith(strip_prefix) else member
    )
    pp = PurePosixPath(rel)
    if pp.is_absolute() or any(part in ("..", "") for part in pp.parts):
        raise ValueError(f"unsafe archive member path: {member!r}")
    target = (dest_dir / Path(*pp.parts)).resolve()
    if dest_dir.resolve() not in target.parents:
        raise ValueError(f"archive member escapes destination: {member!r}")
    return target


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"  # pragma: no cover


def files_digest(files: Iterable[FileRecord]) -> str:
    """SHA-256 over sorted ``<sha256>  <path>`` lines (sha256sum format)."""
    lines = sorted(f"{f.sha256}  {f.path}" for f in files)
    return sha256_bytes(("\n".join(lines) + "\n").encode())


def render_sources_md(manifests: list[dict[str, Any]]) -> str:
    """Render data/SOURCES.md from dataset manifests (deterministic: no wall-clock time)."""
    manifests = sorted(manifests, key=lambda m: m["id"])
    out: list[str] = []
    out.append("# Data sources (generated)")
    out.append("")
    out.append(
        "Generated by `scripts/fetch_datasets.py` from `data/raw/<id>/manifest.json`. "
        "Do not edit by hand. Raw files are never committed; rerun the script to fetch them "
        "and verify the SHA-256 values below. Licences and the allowed-use list live in "
        "`docs/DATA_SOURCES.md`."
    )
    out.append("")
    out.append(
        "Real signals are **mapped onto a synthetic line** (resampled, rescaled, relabelled to "
        "generic tags). Fetch-time transforms are listed here; scenario-level mapping transforms "
        "are recorded per segment in each scenario's `provenance.parquet`."
    )
    out.append("")
    out.append("| ID | Dataset | Licence | Licence checked | Downloaded | Files | Bytes on disk |")
    out.append("|---|---|---|---|---|---|---|")
    for m in manifests:
        lc = m.get("licence_check", {})
        out.append(
            f"| `{m['id']}` | [{m['name']}]({m['url']}) | {m['licence']} | "
            f"{lc.get('checked_date', '?')} ({lc.get('result', '?')}) | {m['downloaded_date']} | "
            f"{len(m['files'])} | {human_bytes(int(m.get('total_bytes', 0)))} |"
        )
    out.append("")
    for m in manifests:
        lc = m.get("licence_check", {})
        files = [FileRecord.from_dict(d) for d in m["files"]]
        out.append(f"## `{m['id']}` — {m['name']}")
        out.append("")
        out.append(f"- **Page:** {m['url']}")
        for u in m.get("download_urls", []):
            out.append(f"- **Download:** {u}")
        out.append(f"- **Licence:** {m['licence']}")
        out.append(
            f"- **Licence check:** {lc.get('result', '?')} on {lc.get('checked_date', '?')} "
            f"against {lc.get('url', '?')} (pattern `{lc.get('pattern', '')}`)"
        )
        out.append(f"- **Downloaded:** {m['downloaded_date']}")
        out.append(f"- **Maps to:** {m.get('maps_to', '')}")
        # the current spec's note wins, so usage notes can be updated without a re-fetch
        note = (SPECS[m["id"]].redistribution_note if m["id"] in SPECS else "") or m.get(
            "redistribution_note", ""
        )
        if note:
            out.append(f"- **Redistribution:** {note}")
        out.append("- **Fetch transforms:**")
        for t in m.get("transforms", []):
            out.append(f"  - {t}")
        out.append("")
        out.append("**Citation (copied from the source page):**")
        out.append("")
        out.append("```text")
        out.append(m["citation"].strip())
        out.append("```")
        out.append("")
        listed = [f for f in files if f.role != "extracted"]
        extracted = [f for f in files if f.role == "extracted"]
        if len(extracted) <= EXTRACTED_SUMMARY_THRESHOLD:
            listed, extracted = files, []
        table = [
            "| File | Role | Bytes | SHA-256 |",
            "|---|---|---|---|",
            *(f"| `{f.path}` | {f.role} | {f.bytes} | `{f.sha256}` |" for f in listed),
        ]
        if len(listed) > 30:
            out.append(f"<details><summary>{len(listed)} files (click to expand)</summary>")
            out.append("")
            out.extend(table)
            out.append("")
            out.append("</details>")
        else:
            out.extend(table)
        if extracted:
            out.append("")
            out.append(
                f"Plus {len(extracted)} extracted files ({human_bytes(sum(f.bytes for f in extracted))}); "
                f"per-file hashes are in `manifest.json`. Digest (SHA-256 over sorted "
                f"`sha256sum` lines): `{files_digest(extracted)}`"
            )
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------------------
# Network helpers
# --------------------------------------------------------------------------------------


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _backoff(attempt: int) -> float:
    return min(60.0, 2.0**attempt) + random.random()


def http_get_text(session: requests.Session, url: str) -> str:
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:
            last = exc
            wait = _backoff(attempt)
            LOG.warning("GET %s failed (%s); retry in %.0fs", url, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}: {last}")


class SlowConnection(requests.ConnectionError):
    """Raised when one connection stays below the minimum throughput (server throttling)."""


class RateMonitor:
    """Flags a stalled connection: < ``min_bps`` averaged over the last ``window_s`` seconds.

    Some servers (UCI, 2026-10) throttle individual connections to ~25 KB/s while fresh
    connections get >1 MB/s, so reconnecting is the fix.
    """

    def __init__(self, min_bps: float, window_s: float, start: float) -> None:
        self.min_bps = min_bps
        self.window_s = window_s
        self.window_start = start
        self.window_bytes = 0

    def feed(self, n: int, now: float) -> bool:
        self.window_bytes += n
        elapsed = now - self.window_start
        if elapsed < self.window_s:
            return False
        stalled = self.window_bytes / elapsed < self.min_bps
        self.window_start, self.window_bytes = now, 0
        return stalled


def download(session: requests.Session, url: str, dest: Path) -> None:
    """Stream ``url`` to ``dest`` via ``dest.part``, resuming with HTTP Range, with retries.

    A connection that stays under ``MIN_RATE_BPS`` for ``RATE_WINDOW_S`` is dropped and
    reopened (at most ``MAX_SLOW_RESTARTS`` times, then the slow rate is accepted).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last: Exception | None = None
    slow_restarts = 0
    for attempt in range(MAX_RETRIES + MAX_SLOW_RESTARTS):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with session.get(
                url, headers=headers, stream=True, timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S)
            ) as r:
                if r.status_code == 416:  # already complete
                    break
                if r.status_code == 429 or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                if have and r.status_code != 206:
                    LOG.info("server ignored Range; restarting %s", dest.name)
                    have = 0
                mode = "ab" if have else "wb"
                total = r.headers.get("Content-Length")
                total_n = int(total) + have if total else None
                done = have
                next_log = time.monotonic() + 10
                monitor = RateMonitor(MIN_RATE_BPS, RATE_WINDOW_S, time.monotonic())
                with part.open(mode) as fh:
                    for block in r.iter_content(CHUNK):
                        fh.write(block)
                        done += len(block)
                        if slow_restarts < MAX_SLOW_RESTARTS and monitor.feed(
                            len(block), time.monotonic()
                        ):
                            slow_restarts += 1
                            raise SlowConnection(
                                f"throughput < {MIN_RATE_BPS / 1024:.0f} KB/s for "
                                f"{RATE_WINDOW_S:.0f}s; reconnecting"
                            )
                        if time.monotonic() >= next_log:
                            pct = f" ({100 * done / total_n:.0f}%)" if total_n else ""
                            LOG.info("  %s: %s%s", dest.name, human_bytes(done), pct)
                            next_log = time.monotonic() + 10
                if total_n is not None and done < total_n:
                    raise requests.ConnectionError(f"short read {done}/{total_n}")
            break
        except requests.RequestException as exc:
            last = exc
            wait = 1.0 if isinstance(exc, SlowConnection) else _backoff(attempt)
            LOG.warning("download %s failed (%s); retry %d in %.0fs", url, exc, attempt + 1, wait)
            time.sleep(wait)
    else:
        raise RuntimeError(f"giving up on {url}: {last}")
    part.replace(dest)


def resolve_redirect(session: requests.Session, url: str) -> str:
    """Follow redirects once (e.g. data.nasa.gov -> short-lived presigned S3 URL)."""
    r = session.get(url, allow_redirects=False, timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
    loc = r.headers.get("Location")
    return loc if r.is_redirect and loc else url


# --------------------------------------------------------------------------------------
# Fetch context + dataset specs
# --------------------------------------------------------------------------------------


@dataclass
class FetchContext:
    raw_dir: Path
    session: requests.Session
    previous: dict[str, FileRecord]
    today: str
    seed: int
    mimii_per_label: int
    records: list[FileRecord] = field(default_factory=list)
    transforms: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def record(self, dataset_dir: Path, path: Path, source: str, role: str = "file") -> FileRecord:
        rel = path.relative_to(dataset_dir).as_posix()
        rec = FileRecord(rel, sha256_file(path), path.stat().st_size, source, role)
        self.records.append(rec)
        return rec


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    name: str
    page_url: str
    licence: str
    licence_check_url: str
    licence_pattern: str
    citation: str
    maps_to: str
    download_urls: tuple[str, ...]
    fetcher: Callable[[DatasetSpec, FetchContext, Path], None] | None
    redistribution_note: str = ""
    optional: bool = False


def _fetch_simple(ctx: FetchContext, ds_dir: Path, url: str, rel: str, role: str = "file") -> Path:
    dest = ds_dir / rel
    if is_up_to_date(dest, ctx.previous.get(rel)):
        LOG.info("  up to date: %s", rel)
    else:
        LOG.info("  downloading %s -> %s", url, rel)
        download(ctx.session, url, dest)
    ctx.record(ds_dir, dest, url, role)
    return dest


def _extract_zip_members(
    ctx: FetchContext,
    ds_dir: Path,
    archive: Path,
    source_url: str,
    keep: Callable[[str], bool],
    flatten: bool = True,
) -> list[Path]:
    """Extract selected members of a local zip, flattened into ``ds_dir`` (zip-slip safe)."""
    out: list[Path] = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir() or not keep(info.filename):
                continue
            if info.filename.startswith("__MACOSX/"):
                continue
            name = PurePosixPath(info.filename).name if flatten else info.filename
            target = safe_member_target(ds_dir, name)
            rel = target.relative_to(ds_dir.resolve()).as_posix()
            if not is_up_to_date(target, ctx.previous.get(rel)):
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
            ctx.record(ds_dir, target, f"{source_url}::{info.filename}", "extracted")
            out.append(target)
    return out


def fetch_metropt3(spec: DatasetSpec, ctx: FetchContext, ds_dir: Path) -> None:
    url = spec.download_urls[0]
    archive = _fetch_simple(ctx, ds_dir, url, "metropt3.zip", role="archive")
    _extract_zip_members(ctx, ds_dir, archive, url, keep=lambda n: n.lower().endswith(".csv"))
    ctx.transforms += [
        "download metropt3.zip from UCI (unmodified)",
        "unzip the CSV member unmodified (flattened into the dataset dir)",
    ]


def fetch_uci_hydraulic(spec: DatasetSpec, ctx: FetchContext, ds_dir: Path) -> None:
    url = spec.download_urls[0]
    archive = _fetch_simple(ctx, ds_dir, url, "uci_hydraulic.zip", role="archive")
    _extract_zip_members(ctx, ds_dir, archive, url, keep=lambda n: n.lower().endswith(".txt"))
    ctx.transforms += [
        "download uci_hydraulic.zip from UCI (unmodified)",
        "unzip all .txt members unmodified (sensor matrices, profile.txt, docs)",
    ]


IMS_TEST_SET = "2nd_test"  # one test set only (DATA_SOURCES.md); the smallest of the three
IMS_MEMBERS = (f"IMS/{IMS_TEST_SET}.rar", "IMS/Readme Document for IMS Bearing Data.pdf")


def _remotezip(url: str):
    try:
        from remotezip import RemoteZip
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise SystemExit(
            "remotezip is required: run with `uv run --extra fetch python scripts/fetch_datasets.py`"
        ) from exc
    return RemoteZip(url, headers={"User-Agent": USER_AGENT}, timeout=READ_TIMEOUT_S)


def _remote_extract(zip_url_resolver: Callable[[], str], members: list[str], targets: list[Path]):
    """Range-extract ``members`` from a remote zip to ``targets`` with retries (CRC-checked)."""
    pending = list(zip(members, targets, strict=True))
    attempt = 0
    while pending:
        try:
            with _remotezip(zip_url_resolver()) as z:
                while pending:
                    member, target = pending[0]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    tmp = target.with_name(target.name + ".part")
                    with z.open(member) as src, tmp.open("wb") as dst:
                        shutil.copyfileobj(src, dst, CHUNK)  # zipfile verifies CRC-32 at EOF
                    tmp.replace(target)
                    pending.pop(0)
                    attempt = 0
        except Exception as exc:  # remotezip raises its own errors; retry broadly
            attempt += 1
            if attempt >= MAX_RETRIES:
                raise RuntimeError(f"remote extract failed: {exc}") from exc
            wait = _backoff(attempt)
            LOG.warning("remote extract error (%s); retry %d in %.0fs", exc, attempt, wait)
            time.sleep(wait)


def fetch_ims_bearings(spec: DatasetSpec, ctx: FetchContext, ds_dir: Path) -> None:
    url = spec.download_urls[0]
    targets = [ds_dir / PurePosixPath(m).name for m in IMS_MEMBERS]
    todo = [
        (m, t)
        for m, t in zip(IMS_MEMBERS, targets, strict=True)
        if not is_up_to_date(t, ctx.previous.get(t.name))
    ]
    if todo:
        LOG.info("  range-extracting %s from IMS.zip (never the whole zip)", [m for m, _ in todo])
        _remote_extract(
            lambda: resolve_redirect(ctx.session, url),
            [m for m, _ in todo],
            [t for _, t in todo],
        )
    for m, t in zip(IMS_MEMBERS, targets, strict=True):
        ctx.record(ds_dir, t, f"{url}::{m}", "archive" if t.suffix == ".rar" else "file")

    rar = targets[0]
    out_dir = ds_dir / IMS_TEST_SET
    marker = out_dir / ".extracted_from_sha256"
    rar_sha = sha256_file(rar)
    if not (marker.exists() and marker.read_text().strip() == rar_sha):
        bsdtar = shutil.which("bsdtar") or shutil.which("tar")
        if not bsdtar:
            raise SystemExit("bsdtar (libarchive) is required to unpack the IMS .rar")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        LOG.info("  unpacking %s with %s", rar.name, bsdtar)
        # libarchive refuses absolute paths and '..' unless -P is given.
        subprocess.run([bsdtar, "-xf", str(rar), "-C", str(out_dir)], check=True)
        marker.write_text(rar_sha + "\n")
    for p in sorted(out_dir.rglob("*")):
        if p.is_file() and p != marker:
            ctx.record(ds_dir, p, f"{url}::IMS/{IMS_TEST_SET}.rar", "extracted")
    ctx.transforms += [
        f"remotezip range-extract of `IMS/{IMS_TEST_SET}.rar` and the readme PDF from IMS.zip "
        "(the 1st and 3rd test sets were never downloaded)",
        f"unpack {IMS_TEST_SET}.rar with bsdtar (libarchive) into `{IMS_TEST_SET}/`, unmodified",
    ]
    ctx.extra["test_set"] = IMS_TEST_SET


MIMII_SNR = "6_dB"
MIMII_MACHINES = ("pump", "fan", "slider", "valve")


def fetch_mimii(spec: DatasetSpec, ctx: FetchContext, ds_dir: Path) -> None:
    selection: dict[str, list[str]] = {}
    for machine in MIMII_MACHINES:
        zip_name = f"{MIMII_SNR}_{machine}.zip"
        url = f"https://zenodo.org/records/3384388/files/{zip_name}?download=1"
        LOG.info("  listing %s (central directory only)", zip_name)
        with _remotezip(url) as z:
            wavs = [i.filename for i in z.infolist() if i.filename.endswith(".wav")]
        chosen: list[str] = []
        for label in ("normal", "abnormal"):
            names = [w for w in wavs if f"/{label}/" in w]
            chosen += select_balanced(
                names, ctx.mimii_per_label, seed=f"{ctx.seed}|{machine}|{label}"
            )
        selection[machine] = chosen
        base = ds_dir / MIMII_SNR
        targets = [safe_member_target(base, m) for m in chosen]
        todo = [
            (m, t)
            for m, t in zip(chosen, targets, strict=True)
            if not is_up_to_date(t, ctx.previous.get(t.relative_to(ds_dir.resolve()).as_posix()))
        ]
        LOG.info("  %s: %d selected, %d to fetch", machine, len(chosen), len(todo))
        for i in range(0, len(todo), 25):
            batch = todo[i : i + 25]
            _remote_extract(lambda u=url: u, [m for m, _ in batch], [t for _, t in batch])
            LOG.info("  %s: %d/%d fetched", machine, min(i + 25, len(todo)), len(todo))
        for m, t in zip(chosen, targets, strict=True):
            ctx.record(ds_dir.resolve(), t, f"{url}::{m}", "file")
    ctx.transforms += [
        f"remotezip range-extract of individual wavs from the {MIMII_SNR} zips for "
        f"{', '.join(MIMII_MACHINES)} (whole zips never downloaded)",
        f"deterministic selection: {ctx.mimii_per_label} normal + {ctx.mimii_per_label} abnormal "
        f"per machine type, spread evenly over machine ids, seeded shuffle (seed {ctx.seed})",
        "wav bytes unmodified (8-channel, 16 kHz, 16-bit)",
    ]
    ctx.extra["selection_seed"] = ctx.seed
    ctx.extra["per_label"] = ctx.mimii_per_label
    ctx.extra["snr"] = MIMII_SNR


MAINTIE_COMMIT = "825e7710e4129598da997276a38b3cb40b200bc2"  # main @ 2024-06-29
MAINTIE_FILES = ("data/gold_release.json", "data/silver_release.json", "LICENSE.md")


def fetch_maintie(spec: DatasetSpec, ctx: FetchContext, ds_dir: Path) -> None:
    for rel in MAINTIE_FILES:
        url = f"https://raw.githubusercontent.com/nlp-tlp/maintie/{MAINTIE_COMMIT}/{rel}"
        _fetch_simple(ctx, ds_dir, url, PurePosixPath(rel).name)
    ctx.transforms += [
        f"download gold/silver JSON + LICENSE.md pinned to commit {MAINTIE_COMMIT} (unmodified)",
    ]
    ctx.extra["commit"] = MAINTIE_COMMIT


SPECS: dict[str, DatasetSpec] = {
    s.id: s
    for s in [
        DatasetSpec(
            id="metropt3",
            name="MetroPT-3 Dataset (UCI #791)",
            page_url="https://archive.ics.uci.edu/dataset/791/metropt+3+dataset",
            licence="CC BY 4.0",
            licence_check_url="https://archive.ics.uci.edu/dataset/791/metropt+3+dataset",
            licence_pattern=r"creativecommons\.org/licenses/by/4\.0",
            citation=(
                "Davari, N., Veloso, B., Ribeiro, R., & Gama, J. (2021). MetroPT-3 Dataset "
                "[Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5VW3R\n\n"
                "Papers the page asks to cite:\n"
                "Davari, N., Veloso, B., Ribeiro, R. P., Pereira, P. M., & Gama, J. (2021). "
                "Predictive maintenance based on anomaly detection using deep learning for air "
                "production unit in the railway industry. 2021 IEEE 8th International Conference "
                "on Data Science and Advanced Analytics (DSAA), 1-10.\n"
                "Veloso, B., Ribeiro, R. P., Gama, J., & Pereira, P. M. (2022). The MetroPT "
                "dataset for predictive maintenance. Scientific Data, 9(1), 764."
            ),
            maps_to="UT-AIR header pressure + compressor current + oil temp; R001-R008",
            download_urls=("https://archive.ics.uci.edu/static/public/791/metropt+3+dataset.zip",),
            fetcher=fetch_metropt3,
        ),
        DatasetSpec(
            id="uci_hydraulic",
            name="Condition Monitoring of Hydraulic Systems (UCI #447)",
            page_url="https://archive.ics.uci.edu/dataset/447/condition+monitoring+of+hydraulic+systems",
            licence="CC BY 4.0",
            licence_check_url="https://archive.ics.uci.edu/dataset/447/condition+monitoring+of+hydraulic+systems",
            licence_pattern=r"creativecommons\.org/licenses/by/4\.0",
            citation=(
                "Helwig, N., Pignanelli, E., & Schütze, A. (2015). Condition monitoring of "
                "hydraulic systems [Dataset]. UCI Machine Learning Repository. "
                "https://doi.org/10.24432/C5CW21\n\n"
                "Related paper: Helwig, N., Pignanelli, E., & Schütze, A. (2015). Condition "
                "monitoring of a complex hydraulic system using multivariate statistics. "
                "IEEE I2MTC 2015. https://doi.org/10.1109/I2MTC.2015.7151267"
            ),
            maps_to="ST10-PRS press hydraulics; R009-R014 (hydraulic_degradation)",
            download_urls=(
                "https://archive.ics.uci.edu/static/public/447/condition+monitoring+of+hydraulic+systems.zip",
            ),
            fetcher=fetch_uci_hydraulic,
        ),
        DatasetSpec(
            id="ims_bearings",
            name="IMS Bearings (Univ. of Cincinnati, via NASA PCoE)",
            page_url="https://catalog.data.gov/dataset/ims-bearings",
            licence="U.S. Government Works (https://www.usa.gov/government-works)",
            licence_check_url="https://catalog.data.gov/dataset/ims-bearings",
            licence_pattern=r"usa\.gov/government-works",
            citation=(
                "J. Lee, H. Qiu, G. Yu, J. Lin, and Rexnord Technical Services (2007). "
                'IMS, University of Cincinnati. "Bearing Data Set", NASA Prognostics Data '
                "Repository, NASA Ames Research Center, Moffett Field, CA\n\n"
                "Reference paper (from the bundled readme): Hai Qiu, Jay Lee, Jing Lin. "
                '"Wavelet Filter-based Weak Signature Detection Method and its Application on '
                'Roller Bearing Prognostics." Journal of Sound and Vibration 289 (2006) 1066-1090'
            ),
            maps_to="ST50-CNV conveyor vibration; R015-R017; raw snapshots feed spectrum()",
            download_urls=("https://data.nasa.gov/docs/legacy/IMS.zip",),
            fetcher=fetch_ims_bearings,
        ),
        DatasetSpec(
            id="mimii",
            name="MIMII: Sound Dataset for Malfunctioning Industrial Machine Investigation and Inspection (Zenodo 3384388)",
            page_url="https://zenodo.org/records/3384388",
            licence="CC BY-SA 4.0",
            licence_check_url="https://zenodo.org/api/records/3384388",
            licence_pattern=r'"cc-by-sa-4\.0"',
            citation=(
                "Harsh Purohit, Ryo Tanabe, Kenji Ichige, Takashi Endo, Yuki Nikaido, Kaori "
                'Suefusa, and Yohei Kawaguchi, "MIMII Dataset: Sound Dataset for Malfunctioning '
                'Industrial Machine Investigation and Inspection," arXiv preprint '
                "arXiv:1909.09347, 2019.\n"
                "Harsh Purohit, Ryo Tanabe, Kenji Ichige, Takashi Endo, Yuki Nikaido, Kaori "
                'Suefusa, and Yohei Kawaguchi, "MIMII Dataset: Sound Dataset for Malfunctioning '
                'Industrial Machine Investigation and Inspection," in Proc. 4th Workshop on '
                "Detection and Classification of Acoustic Scenes and Events (DCASE), 2019.\n"
                "Dataset DOI: 10.5281/zenodo.3384388 (Hitachi, Ltd.)"
            ),
            maps_to="listen(): pump->ST40, slider->ST50, fan->ST20/ST30 cooling, valve->UT-AIR",
            download_urls=tuple(
                f"https://zenodo.org/records/3384388/files/{MIMII_SNR}_{m}.zip (range-extracted)"
                for m in MIMII_MACHINES
            ),
            fetcher=fetch_mimii,
            redistribution_note=(
                "CC BY-SA 4.0 share-alike: clips we redistribute and any derived audio dataset "
                "stay CC BY-SA 4.0 with this attribution. Usage: `simulator/audio.py` downmixes "
                "each clip to mono (mean of the 8 channels, 16 kHz, 16-bit; some get added plant "
                "background noise) and serves it from "
                "`gs://andon-511816-assets/audio/{scenario_id}/{asset_id}/{ts}.wav` "
                "(object metadata `licence: CC BY-SA 4.0`); each placement has a provenance row. "
                "MIMII DUE/DG (CC BY-NC-SA) are NOT used."
            ),
        ),
        DatasetSpec(
            id="maintie",
            name="MaintIE (nlp-tlp/maintie)",
            page_url="https://github.com/nlp-tlp/maintie",
            licence="MIT",
            licence_check_url="https://api.github.com/repos/nlp-tlp/maintie/license",
            licence_pattern=r'"spdx_id"\s*:\s*"MIT"',
            citation=(
                "@inproceedings{bikaun-etal-2024-maintie-fine,\n"
                "  author    = {Bikaun, Tyler K. and French, Tim and Stewart, Michael and "
                "Liu, Wei and Hodkiewicz, Melinda},\n"
                "  title     = {MaintIE: A Fine-Grained Annotation Schema and Benchmark for "
                "Information Extraction from Maintenance Short Texts},\n"
                "  booktitle = {Proceedings of the 2024 Joint International Conference on "
                "Computational Linguistics, Language Resources and Evaluation (LREC-COLING 2024)},\n"
                "  month     = may,\n"
                "  year      = {2024},\n"
                "  address   = {Torino, Italia},\n"
                "  publisher = {ELRA and ICCL},\n"
                "  pages     = {10939--10951},\n"
                "  url       = {https://aclanthology.org/2024.lrec-main.954}\n"
                "}"
            ),
            maps_to="few-shot style exemplars for the work-order generator (not our plant history)",
            download_urls=tuple(
                f"https://raw.githubusercontent.com/nlp-tlp/maintie/{MAINTIE_COMMIT}/{f}"
                for f in MAINTIE_FILES
            ),
            fetcher=fetch_maintie,
        ),
        DatasetSpec(
            id="bosch_cnc",
            name="Bosch CNC Machining (UCI #752)",
            page_url="https://archive.ics.uci.edu/dataset/752/bosch+cnc+machining+dataset",
            licence="CC BY 4.0 (data folder)",
            licence_check_url="https://archive.ics.uci.edu/dataset/752/bosch+cnc+machining+dataset",
            licence_pattern=r"creativecommons\.org/licenses/by/4\.0",
            citation="Tnani, Feil, Diepold (Procedia CIRP 2022) + UCI",
            maps_to="optional second vibration texture for ST10/ST20",
            download_urls=(),
            fetcher=None,
            optional=True,
        ),
    ]
}

# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def licence_check(session: requests.Session, spec: DatasetSpec, today: str) -> dict[str, Any]:
    text = http_get_text(session, spec.licence_check_url)
    ok = check_licence_text(text, spec.licence_pattern)
    return {
        "url": spec.licence_check_url,
        "pattern": spec.licence_pattern,
        "expected": spec.licence,
        "checked_date": today,
        "result": "match" if ok else "MISMATCH",
    }


def fetch_one(
    spec: DatasetSpec, raw_dir: Path, args: argparse.Namespace, session: requests.Session
) -> bool:
    LOG.info("== %s (%s)", spec.id, spec.name)
    if spec.fetcher is None:
        LOG.warning("  %s is optional and has no fetcher yet; skipped", spec.id)
        return True
    ds_dir = (raw_dir / spec.id).resolve()
    ds_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = ds_dir / MANIFEST_NAME
    prev_manifest = load_manifest(manifest_path)

    if args.skip_licence_check:
        lc = (prev_manifest or {}).get("licence_check") or {
            "url": spec.licence_check_url,
            "pattern": spec.licence_pattern,
            "expected": spec.licence,
            "checked_date": "not checked",
            "result": "skipped",
        }
    else:
        lc = licence_check(session, spec, args.licence_checked_date)
        LOG.info("  licence %s: %s (%s)", spec.licence, lc["result"], spec.licence_check_url)
        if lc["result"] != "match":
            LOG.error(
                "  LICENCE MISMATCH for %s: expected %s at %s. Stopping this dataset; "
                "update docs/DATA_SOURCES.md only after a human review.",
                spec.id,
                spec.licence,
                spec.licence_check_url,
            )
            return False

    ctx = FetchContext(
        raw_dir=raw_dir,
        session=session,
        previous=manifest_index(prev_manifest),
        today=args.licence_checked_date,
        seed=args.seed,
        mimii_per_label=args.mimii_per_label,
    )
    spec.fetcher(spec, ctx, ds_dir)
    unchanged = prev_manifest is not None and {(f.path, f.sha256) for f in ctx.records} == {
        (d["path"], d["sha256"]) for d in prev_manifest.get("files", [])
    }
    downloaded = prev_manifest["downloaded_date"] if unchanged and prev_manifest else ctx.today
    manifest = build_manifest(
        spec=spec,
        licence_check=lc,
        downloaded_date=downloaded,
        files=ctx.records,
        transforms=ctx.transforms,
        extra=ctx.extra,
    )
    write_manifest(manifest_path, manifest)
    LOG.info(
        "  %s: %d files, %s on disk",
        spec.id,
        len(ctx.records),
        human_bytes(manifest["total_bytes"]),
    )
    return True


def collect_manifests(raw_dir: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(raw_dir.glob(f"*/{MANIFEST_NAME}")):
        m = load_manifest(p)
        if m and m.get("id") in SPECS:
            out.append(m)
    return out


def default_raw_dir() -> Path:
    env = os.environ.get("DATA_RAW_DIR")
    if env:
        p = Path(env).expanduser()
        return p if p.is_absolute() else (REPO_ROOT / p)
    return REPO_ROOT / "data" / "raw"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--only",
        default="metropt3,uci_hydraulic,ims_bearings,mimii,maintie",
        help=f"comma list of dataset ids; known: {','.join(SPECS)}",
    )
    ap.add_argument("--raw-dir", type=Path, default=None, help="default: $DATA_RAW_DIR or data/raw")
    ap.add_argument("--sources-md", type=Path, default=REPO_ROOT / "data" / "SOURCES.md")
    ap.add_argument("--seed", type=int, default=2026, help="MIMII clip selection seed")
    ap.add_argument("--mimii-per-label", type=int, default=50)
    ap.add_argument(
        "--licence-checked-date",
        default=dt.date.today().isoformat(),
        help="date recorded for the licence check (default: today)",
    )
    ap.add_argument(
        "--skip-licence-check",
        action="store_true",
        help="reuse the last recorded licence check (offline reruns only)",
    )
    ap.add_argument(
        "--render-only", action="store_true", help="only re-render SOURCES.md from manifests"
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    ids = [s.strip() for s in args.only.split(",") if s.strip()]
    unknown = [i for i in ids if i not in SPECS]
    if unknown:
        ap.error(
            f"unknown dataset id(s): {unknown}; allowed (DATA_SOURCES.md USE list): {list(SPECS)}"
        )
    args.ids = ids
    args.raw_dir = (args.raw_dir or default_raw_dir()).expanduser().resolve()
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    LOG.info("raw dir: %s", args.raw_dir)
    ok = True
    if not args.render_only:
        session = make_session()
        for ds_id in args.ids:
            try:
                ok = fetch_one(SPECS[ds_id], args.raw_dir, args, session) and ok
            except Exception:
                LOG.exception("  %s failed", ds_id)
                ok = False
    manifests = collect_manifests(args.raw_dir)
    args.sources_md.parent.mkdir(parents=True, exist_ok=True)
    args.sources_md.write_text(render_sources_md(manifests), encoding="utf-8")
    LOG.info("wrote %s (%d datasets)", args.sources_md, len(manifests))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
