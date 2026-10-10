"""Offline tests for the pure helpers in scripts/fetch_datasets.py (no network)."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_datasets.py"
_spec = importlib.util.spec_from_file_location("fetch_datasets", _PATH)
assert _spec and _spec.loader
fd = importlib.util.module_from_spec(_spec)
sys.modules["fetch_datasets"] = fd
_spec.loader.exec_module(fd)


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    data = b"andon" * 300_000  # > 1 chunk
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    assert fd.sha256_file(p, chunk_size=4096) == hashlib.sha256(data).hexdigest()


def test_is_up_to_date(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes(b"hello")
    rec = fd.FileRecord("a.txt", hashlib.sha256(b"hello").hexdigest(), 5, "u")
    assert fd.is_up_to_date(p, rec)
    assert not fd.is_up_to_date(p, None)
    assert not fd.is_up_to_date(tmp_path / "missing", rec)
    p.write_bytes(b"hellO")  # same size, different content
    assert not fd.is_up_to_date(p, rec)


def _manifest(tmp_path: Path) -> dict:
    spec = fd.SPECS["maintie"]
    files = [
        fd.FileRecord("z.json", "b" * 64, 20, "https://x/z"),
        fd.FileRecord("a.json", "a" * 64, 10, "https://x/a"),
    ]
    lc = {
        "url": spec.licence_check_url,
        "pattern": spec.licence_pattern,
        "expected": spec.licence,
        "checked_date": "2026-10-11",
        "result": "match",
    }
    return fd.build_manifest(
        spec=spec,
        licence_check=lc,
        downloaded_date="2026-10-11",
        files=files,
        transforms=["download unmodified"],
    )


def test_manifest_roundtrip_sorted_and_totalled(tmp_path: Path) -> None:
    m = _manifest(tmp_path)
    assert [f["path"] for f in m["files"]] == ["a.json", "z.json"]
    assert m["total_bytes"] == 30
    assert m["licence"] == "MIT"
    path = tmp_path / "maintie" / "manifest.json"
    fd.write_manifest(path, m)
    loaded = fd.load_manifest(path)
    assert loaded == m
    idx = fd.manifest_index(loaded)
    assert idx["a.json"].sha256 == "a" * 64
    assert fd.manifest_index(None) == {}


def test_load_manifest_corrupt_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "manifest.json"
    p.write_text("{not json")
    assert fd.load_manifest(p) is None
    assert fd.load_manifest(tmp_path / "nope.json") is None


def test_render_sources_md_contains_required_fields(tmp_path: Path) -> None:
    md = fd.render_sources_md([_manifest(tmp_path)])
    for needle in [
        "# Data sources (generated)",
        "https://github.com/nlp-tlp/maintie",
        "MIT",
        "2026-10-11",
        "a" * 64,
        "`a.json`",
        "download unmodified",
        "bikaun-etal-2024-maintie-fine",
        "mapped onto a synthetic line",
    ]:
        assert needle in md
    # Deterministic: same input, same bytes.
    assert md == fd.render_sources_md([_manifest(tmp_path)])


def test_render_summarises_many_extracted_files() -> None:
    spec = fd.SPECS["ims_bearings"]
    files = [fd.FileRecord("x.rar", "c" * 64, 5, "u", "archive")] + [
        fd.FileRecord(f"2nd_test/f{i:04d}", f"{i:064x}", 1, "u", "extracted") for i in range(80)
    ]
    m = fd.build_manifest(
        spec=spec,
        licence_check={"checked_date": "2026-10-11", "result": "match"},
        downloaded_date="2026-10-11",
        files=files,
        transforms=[],
    )
    md = fd.render_sources_md([m])
    assert "`x.rar`" in md
    assert "Plus 80 extracted files" in md
    assert fd.files_digest([f for f in files if f.role == "extracted"]) in md
    assert "2nd_test/f0005" not in md


def test_check_licence_text() -> None:
    assert fd.check_licence_text(
        '<a href="https://creativecommons.org/licenses/by/4.0/legalcode">',
        fd.SPECS["metropt3"].licence_pattern,
    )
    assert not fd.check_licence_text(
        "creativecommons.org/licenses/by-nc/4.0", fd.SPECS["metropt3"].licence_pattern
    )
    assert fd.check_licence_text('{"id": "cc-by-sa-4.0"}', fd.SPECS["mimii"].licence_pattern)
    assert not fd.check_licence_text('{"id": "cc-by-nc-sa-4.0"}', fd.SPECS["mimii"].licence_pattern)
    assert fd.check_licence_text('"spdx_id": "MIT"', fd.SPECS["maintie"].licence_pattern)


def test_select_balanced_deterministic_and_spread() -> None:
    names = [f"pump/id_{i:02d}/normal/{j:08d}.wav" for i in (0, 2, 4, 6) for j in range(100)]
    a = fd.select_balanced(names, 50, seed="2026|pump|normal")
    b = fd.select_balanced(list(reversed(names)), 50, seed="2026|pump|normal")
    assert a == b  # independent of listing order
    assert len(a) == 50 == len(set(a))
    per_id = {i: sum(f"id_{i:02d}" in n for n in a) for i in (0, 2, 4, 6)}
    assert sorted(per_id.values()) == [12, 12, 13, 13]
    assert fd.select_balanced(names, 50, seed="other") != a


def test_select_balanced_caps_small_groups() -> None:
    names = ["m/id_00/abnormal/1.wav", "m/id_00/abnormal/2.wav", "m/id_02/abnormal/1.wav"]
    assert fd.select_balanced(names, 10, seed="s") == sorted(names)
    assert fd.select_balanced([], 10, seed="s") == []


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/passwd", "a/../../b", ""])
def test_safe_member_target_rejects_traversal(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        fd.safe_member_target(tmp_path, bad)


def test_safe_member_target_ok(tmp_path: Path) -> None:
    t = fd.safe_member_target(tmp_path, "pump/id_00/normal/00000001.wav")
    assert t == (tmp_path / "pump/id_00/normal/00000001.wav").resolve()


def test_cli_rejects_unknown_dataset() -> None:
    with pytest.raises(SystemExit):
        fd.parse_args(["--only", "paderborn"])


def test_cli_defaults_raw_dir_inside_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_RAW_DIR", raising=False)
    args = fd.parse_args(["--only", "maintie"])
    assert args.ids == ["maintie"]
    assert args.raw_dir == (fd.REPO_ROOT / "data" / "raw").resolve()


def test_spec_registry_matches_use_list() -> None:
    use_list = {"metropt3", "uci_hydraulic", "ims_bearings", "mimii", "maintie", "bosch_cnc"}
    assert set(fd.SPECS) == use_list
    for s in fd.SPECS.values():
        assert s.licence and s.citation and s.page_url.startswith("https://")


def test_rate_monitor_flags_stalled_connection() -> None:
    m = fd.RateMonitor(min_bps=1000, window_s=10, start=0.0)
    assert not m.feed(500, 5.0)  # window not complete yet
    assert m.feed(500, 10.0)  # 1000 B / 10 s = 100 B/s < 1000
    assert not m.feed(50_000, 20.0)  # next window is fast
