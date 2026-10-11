"""One diagnosis in the terminal: ``uv run python -m agents.cli --scenario S001 [--verbose]``.

Pretty-prints the contract event stream (plan -> tool calls with provenance chips -> verdicts ->
RCA -> work order with LOTO -> cost). ``--json`` prints the raw events (JSONL). ``--mode replay``
replays ``tests/fixtures/llm/<scenario>/`` at $0; ``--record`` runs live and saves fixtures there.
``--force-bad-claim`` is a test hook: it inflates one numeric claim of the first draft so the
verifier's rejection is demonstrable; the output labels it. Ground truth is never read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import config
from agents.runtime import FIXTURE_ROOT

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "andon.duckdb"


def _chips(prov: list[dict]) -> str:
    out = []
    for p in prov:
        if p.get("real"):
            out.append(f"[REAL {p.get('source_id')}]")
        else:
            out.append("[SYNTHETIC]")
    return " ".join(dict.fromkeys(out)) or "[no provenance]"


def _short(obj: Any, n: int = 260) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[: n - 3] + "..."


def _wrap(s: str, indent: str) -> str:
    return textwrap.fill(s, width=110, initial_indent=indent, subsequent_indent=indent + "  ")


class Printer:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.forced: str | None = None
        self.mode = "live"
        self.calls: dict[str, str] = {}
        self.final_verdicts: dict[str, str] = {}

    def __call__(self, ev: Any) -> None:
        d = ev.data.model_dump(mode="json") if hasattr(ev.data, "model_dump") else ev.data
        getattr(self, f"on_{ev.type}", self.other)(ev, d)

    def other(self, ev: Any, d: dict) -> None:
        print(f"  ({ev.type}) {_short(d)}")

    def on_incident_started(self, ev: Any, d: dict) -> None:
        self.mode = d["mode"]
        print(f"== {ev.incident_id} | scenario {d['scenario_id']} | line {d['line_id']} stopped at "
              f"{d['stopped_station']} | mode {d['mode']} ==")  # fmt: skip
        print("   SYNTHETIC LINE · REAL SIGNALS MARKED")

    def on_agent_started(self, ev: Any, d: dict) -> None:
        print(f"\n>> {d['agent']} started ({d['model_id'] or 'deterministic'})")

    def on_agent_finished(self, ev: Any, d: dict) -> None:
        print(f"<< {d['agent']} finished ({d['model_id'] or 'deterministic'})")

    def on_plan(self, ev: Any, d: dict) -> None:
        print("   PLAN")
        for i, s in enumerate(d["steps"], 1):
            print(_wrap(f"{i}. {s}", "     "))

    def on_tool_call(self, ev: Any, d: dict) -> None:
        self.calls[d["call_id"]] = d["tool"]
        args = _short(d["args"], 400 if self.verbose else 160)
        print(f"   [{ev.agent}] call {d['tool']}({args})")

    def on_tool_result(self, ev: Any, d: dict) -> None:
        tool = self.calls.get(d["call_id"], "?")
        if not d["evidence_id"]:
            print(f"     -> {tool}: {_short(d['summary'], 300)}  ({d['latency_ms']} ms)")
            return
        print(f"     -> {d['evidence_id']} {_chips(d['provenance'])} ({d['latency_ms']} ms)")
        if self.verbose:
            print(_wrap(_short(d["summary"], 700), "        "))
            for p in d["provenance"]:
                if p.get("real"):
                    print(_wrap(f"provenance: {p.get('source_ref')}", "        "))

    def on_cache_hit(self, ev: Any, d: dict) -> None:
        print(
            f"     cache hit: {d['cached_tokens']} manual tokens from cache, saved ${d['saved_usd']:.4f}"
        )

    def on_model_fallback(self, ev: Any, d: dict) -> None:
        print(f"   MODEL FALLBACK {d['from_model']} -> {d['to_model']} ({d['reason']})")

    def on_hypotheses(self, ev: Any, d: dict) -> None:
        print(f"   DRAFT ({d['status']})")
        self.forced = None
        for i, h in enumerate(d["hypotheses"], 1):
            print(f"     H{i} {h['cause_class']} @ {h['asset_id']}  conf {h['confidence']:.2f}  chain {' -> '.join(h['causal_chain'])}")  # fmt: skip
            if self.verbose:
                for c in h["claims"]:
                    print(_wrap(f"- {c['claim_id']} [{c['kind']}] {c['text']} {c['evidence_ids']}", "        "))  # fmt: skip
                if h.get("refuting_evidence_ids"):
                    print(f"        refuting: {h['refuting_evidence_ids']}")
            for c in h["claims"]:
                if "TEST HOOK" in c["text"]:
                    self.forced = c["claim_id"]
        if self.forced:
            print(
                f"     ** TEST HOOK --force-bad-claim: claim {self.forced} was inflated on purpose **"
            )

    def on_claim_verdict(self, ev: Any, d: dict) -> None:
        tag = {"pass": "PASS", "fail": "FAIL", "unverifiable": "UNVERIFIABLE"}[d["verdict"]]
        mark = "  <- forced bad claim (test hook)" if d["claim_id"] == self.forced else ""
        mv = f" measured={d['measured_value']}" if d.get("measured_value") is not None else ""
        self.final_verdicts[d["claim_id"]] = d["verdict"]
        print(_wrap(f"{tag:12s} {d['claim_id']}: {d['reason']}{mv}{mark}", "     "))

    def on_verifier_verdict(self, ev: Any, d: dict) -> None:
        print(f"   VERIFIER iteration {d['iteration']}: {d['overall']}")

    def on_rca_final(self, ev: Any, d: dict) -> None:
        print(f"\n== RCA ({d['status'].upper()}) ==")
        for i, h in enumerate(d["hypotheses"], 1):
            print(f"  H{i} {h['cause_class']} @ {h['asset_id']}  confidence {h['confidence']:.2f}")
            print(f"     chain: {' -> '.join(h['causal_chain'])}")
            for c in h["claims"]:
                v = self.final_verdicts.get(c["claim_id"], "?")
                text = c["text"] if v == "pass" else f"~~{c['text']}~~ ({v})"
                print(_wrap(f"- {text}", "     "))
            if h.get("next_check"):
                print(_wrap(f"next check: {h['next_check']}", "     "))

    def on_work_order_draft(self, ev: Any, d: dict) -> None:
        print(
            f"\n== WORK ORDER {d['wo_id']} [{d['status']}] {d['cause_class']} @ {d['asset_id']} =="
        )
        for s in d["steps"]:
            if s["is_safety"]:
                c = s["citation"]
                print(
                    _wrap(
                        f'{s["order"]:2d}. [SAFETY, {c["doc"]} p.{c["page"]}] "{s["text"]}"', "  "
                    )
                )
            else:
                print(_wrap(f"{s['order']:2d}. {s['text']}", "  "))
        if d["parts"]:
            print(f"  parts: {', '.join(d['parts'])}")

    def on_cost(self, ev: Any, d: dict) -> None:
        if self.mode == "replay":
            print("\n   (replay: cost below is the recorded usage; nothing was billed)")
        by = ", ".join(f"{k} ${v:.4f}" for k, v in d["by_model"].items())
        print(f"\n== COST ${d['usd']:.4f} | in {d['input_tokens']} (cached {d['cached_tokens']}) "
              f"out {d['output_tokens']} tokens | {by} ==")  # fmt: skip

    def on_error(self, ev: Any, d: dict) -> None:
        print(f"\n!! ERROR {d['code']}: {d['message']} (retryable={d['retryable']})")

    def on_done(self, ev: Any, d: dict) -> None:
        print(f"== DONE in {d['duration_ms'] / 1000:.1f} s ==")


async def _run(args: argparse.Namespace) -> int:
    from agents.events_map import run_incident
    from agents.graph import build_app
    from agents.llm import get_llm
    from simulator.load import DuckDBStore

    if args.gcloud_token:
        from agents.cache import _gcloud_credentials

        get_llm().credentials = _gcloud_credentials()
    mode = "record" if args.record else args.mode
    store = DuckDBStore(args.db)
    stages = (
        tuple(args.stages.split(","))
        if args.stages
        else ("commander", "evidence", "rca_loop", "drafter")
    )
    from agents.cmms import InMemoryCMMS, default_cmms

    cmms = InMemoryCMMS() if mode == "replay" else default_cmms()  # live drafts -> JSONL/Firestore
    app = build_app(store, judge_model=args.judge_model, mode=mode, stages=stages, cmms=cmms)
    record_dir = (
        (Path(args.record_dir) if args.record_dir else FIXTURE_ROOT / args.scenario)
        if args.record
        else None
    )
    printer = Printer(args.verbose)
    status = 0
    t0 = time.perf_counter()
    try:
        async for ev in run_incident(app, args.scenario, force_bad_claim=args.force_bad_claim,
                                     record_dir=record_dir):  # fmt: skip
            if args.json:
                print(ev.model_dump_json())
            else:
                printer(ev)
            if ev.type == "error":
                status = 2
    finally:
        store.close()
    if not args.json:
        print(
            f"(wall clock {time.perf_counter() - t0:.1f} s; spent today ${get_llm().spend.spent_today():.4f})"
        )
        if record_dir:
            print(f"(fixtures saved to {record_dir})")
    return status


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agents.cli", description=__doc__.split("\n")[0])
    p.add_argument("--scenario", required=True)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--json", action="store_true", help="print raw contract events (JSONL)")
    p.add_argument("--judge-model", choices=sorted(config.PINNED_MODELS), default=None)
    p.add_argument("--force-bad-claim", action="store_true", help="TEST HOOK: inflate one claim")
    p.add_argument("--mode", choices=("live", "replay"), default="live")
    p.add_argument("--record", action="store_true", help="live run that saves LLM fixtures")
    p.add_argument("--record-dir", default=None)
    p.add_argument("--stages", default=None, help="e.g. commander,evidence (skeleton run)")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--gcloud-token", action="store_true", help="use the gcloud login, not ADC")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if not args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)  # fmt: skip
    for noisy in ("google_adk", "google.adk", "httpx", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
