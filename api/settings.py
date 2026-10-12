"""API settings, read once from the environment (Cloud Run injects secrets as env vars).

No secret has a default and none is ever logged: ``repr`` of :class:`Settings` hides the passcode.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parents[1]


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    store_backend: str = config.STORE_BACKEND  # duckdb (local) | gcs (published Parquet, ADR-021)
    allowed_origins: tuple[str, ...] = tuple(config.ALLOWED_ORIGINS)
    daily_budget_usd: float = config.DAILY_BUDGET_USD
    demo_passcode: str = field(default="", repr=False)  # empty = live mode disabled
    firestore: bool = False
    replay_only: bool = False
    live_runs_per_day: int = 30
    live_runs_per_min_per_ip: int = 3
    replay_runs_per_min_per_ip: int = 20  # anonymous replays; not counted against the live quota
    max_concurrent_replay: int = 8  # per instance
    max_concurrent_live: int = 2  # per instance; each live run holds an ADK graph in memory
    trusted_proxy_hops: int = 1  # Cloud Run appends the real peer: take XFF[-hops]
    heartbeat_s: float = 15.0
    run_timeout_s: float = 840.0  # below Cloud Run's 900 s request timeout
    replay_gap_cap_s: float = 3.0
    max_body_bytes: int = 64 * 1024
    enable_stretch: frozenset[str] = config.ENABLE_STRETCH  # e.g. {'upload'}; see DEVELOPMENT.md 9b
    uploads_per_day: int = 30  # stretch: CSV uploads per instance per IST day (all IPs)
    confirms_per_min_per_ip: int = 10
    uploads_per_ip_per_day: int = 10  # stretch: CSV uploads per IP per IST day
    confirms_per_day: int = 60  # stretch: confirm calls per instance per IST day
    voice_notes_per_min_per_ip: int = 3  # stretch: technician voice notes
    voice_notes_per_day: int = 100  # per instance per IST day (all IPs)
    lang_per_min_per_ip: int = 20  # stretch: work-order translations (cache hits count too)
    lang_per_day: int = 300  # per instance per IST day (all IPs)
    replay_dir: Path = ROOT / "data" / "replays"
    audit_dir: Path = ROOT / "data" / "audit"  # local (non-Firestore) audit files
    cmms_path: Path = ROOT / "data" / "cmms" / "work_orders.jsonl"
    eval_latest: Path = ROOT / "eval" / "results" / "latest.json"
    sources_md: Path = ROOT / "data" / "SOURCES.md"
    local_db: Path = ROOT / "data" / "andon.duckdb"

    def __post_init__(self) -> None:
        if any(o.strip() == "*" for o in self.allowed_origins):
            raise ValueError("ALLOWED_ORIGINS must list explicit origins, never '*'")

    @property
    def upload_enabled(self) -> bool:
        return "upload" in self.enable_stretch

    @property
    def tech_enabled(self) -> bool:
        return "tech" in self.enable_stretch

    @property
    def lang_enabled(self) -> bool:
        return "lang" in self.enable_stretch

    @property
    def live_enabled(self) -> bool:
        return bool(self.demo_passcode) and not self.replay_only

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        backend = e.get("STORE_BACKEND", config.STORE_BACKEND)
        origins = tuple(o.strip() for o in e.get("ALLOWED_ORIGINS", "").split(",") if o.strip())
        return cls(
            store_backend=backend,
            allowed_origins=origins or tuple(config.ALLOWED_ORIGINS),
            daily_budget_usd=float(e.get("DAILY_BUDGET_USD", config.DAILY_BUDGET_USD)),
            demo_passcode=e.get("DEMO_PASSCODE", ""),
            firestore=_bool(e.get("FIRESTORE"), backend in ("gcs", "bigquery")),
            replay_only=_bool(e.get("REPLAY_ONLY"), False),
            voice_notes_per_min_per_ip=int(e.get("VOICE_NOTES_PER_MIN_PER_IP", 3)),
            voice_notes_per_day=int(e.get("VOICE_NOTES_PER_DAY", 100)),
            lang_per_min_per_ip=int(e.get("LANG_PER_MIN_PER_IP", 20)),
            lang_per_day=int(e.get("LANG_PER_DAY", 300)),
            live_runs_per_day=int(e.get("LIVE_RUNS_PER_DAY", 30)),
            live_runs_per_min_per_ip=int(e.get("LIVE_RUNS_PER_MIN_PER_IP", 3)),
            max_concurrent_live=int(e.get("MAX_CONCURRENT_LIVE", 2)),
            replay_runs_per_min_per_ip=int(e.get("REPLAY_RUNS_PER_MIN_PER_IP", 20)),
            max_concurrent_replay=int(e.get("MAX_CONCURRENT_REPLAY", 8)),
            trusted_proxy_hops=int(e.get("TRUSTED_PROXY_HOPS", 1)),
            heartbeat_s=float(e.get("HEARTBEAT_S", 15)),
            run_timeout_s=float(e.get("RUN_TIMEOUT_S", 840)),
            replay_dir=Path(e.get("REPLAY_DIR", ROOT / "data" / "replays")),
            audit_dir=Path(e.get("AUDIT_DIR", ROOT / "data" / "audit")),
            cmms_path=Path(e.get("CMMS_PATH", ROOT / "data" / "cmms" / "work_orders.jsonl")),
        )
