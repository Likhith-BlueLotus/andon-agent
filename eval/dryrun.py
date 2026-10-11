"""``--dry-run``: the whole harness end to end with mocked LLMs, at $0.

* S1/S2/S3 run the **real graph, tools, verifier and drafter** in replay mode against the
  hand-written templated fixture ``tests/fixtures/llm/_templates/S801_air`` (materialised per
  scenario against the real store). Every scenario therefore gets the same "air pressure drop"
  story; scenarios where the template's placeholders cannot be resolved get no fixture and end as
  error rows (which exercises the failed-run path).
* B1 uses :class:`MockB1Transport`: a deterministic fake Gemini that reads the evidence in the prompt
  and writes an RCAReport (some wrong classes, some inflated numbers, some claims without evidence).
* B2 is real (it never calls an LLM).

Accuracy numbers from a dry run mean nothing; the report is stamped DRY RUN. The mock may look at
nothing but the prompt: it never reads ground truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

TEMPLATE = "S801_air"


def prepare_fixtures(store: Any, ids: list[str], out_root: Path) -> list[str]:
    """Materialise the template for each scenario; returns the ids that resolved."""
    try:
        from tests import llm_replay
        from tests.llm_replay import materialise
    except ImportError as exc:  # pragma: no cover - dry-run is a repo-checkout tool
        raise RuntimeError(
            "--dry-run needs the repo's tests/ package (tests/llm_replay.py)"
        ) from exc
    real_get = llm_replay._get

    def safe_get(obj: Any, path: str) -> Any:
        # the template assumes an air-pressure story; where the data has no such change point the
        # placeholder resolves to 0 and the claim fails verification (a realistic miss)
        try:
            return real_get(obj, path)
        except (IndexError, KeyError, TypeError):
            return 0

    llm_replay._get = safe_get
    ok = []
    try:
        ok = _materialise_all(materialise, store, ids, out_root)
    finally:
        llm_replay._get = real_get
    return ok


def _materialise_all(materialise: Any, store: Any, ids: list[str], out_root: Path) -> list[str]:
    ok = []
    for sid in ids:
        try:
            d = materialise(TEMPLATE, store, sid, out_root)
            _pad_drafts(d)
            ok.append(sid)
        except Exception:
            continue
    return ok


def _h(s: str, mod: int) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16) % mod


class MockB1Transport:
    """``agents.llm.Transport``: (model_id, contents, config) -> fake GenerateContentResponse."""

    async def __call__(self, model_id: str, contents: Any, gen_config: Any) -> Any:
        prompt = contents if isinstance(contents, str) else str(contents)
        sid = (re.search(r"scenario ([SR]\d{3})", prompt) or [None, "S000"])[1]
        m = re.search(r"<evidence>\n(.*?)\n</evidence>", prompt, re.S)
        evidence = json.loads(m.group(1)) if m else []
        report = self.report(sid, evidence)
        toks = max(len(prompt) // 4, 1)
        usage = SimpleNamespace(
            prompt_token_count=toks,
            candidates_token_count=1500,
            thoughts_token_count=2500,
            cached_content_token_count=0,
        )
        return SimpleNamespace(text=json.dumps(report), usage_metadata=usage, candidates=[])

    @staticmethod
    def report(sid: str, evidence: list[dict]) -> dict:
        pick = _h(sid, 10)
        cls, asset = (
            ("air_pressure_drop", "UT-AIR")
            if pick < 6
            else ("weld_tip_wear", "ST20-WLD")
            if pick < 8
            else ("no_fault", "ST20-WLD")
        )
        ev = next(
            (
                e
                for e in evidence
                if e["tool"] == "anomaly_score"
                and e["args"].get("asset_id") == asset
                and isinstance(e["summary"].get("score"), int | float)
            ),
            None,
        )
        claims = []
        if ev is not None:
            val = ev["summary"]["score"]
            if _h(sid + "bad", 3) == 0:
                val = round(val * 1.5 + 0.2, 3)  # an inflated number: the checker must catch it
            claims.append(
                {
                    "claim_id": "h1c1",
                    "kind": "numeric",
                    "evidence_ids": [ev["evidence_id"]],
                    "asserted_value": val,
                    "text": f"{asset} anomaly score {val} path: score",
                }
            )
        claims.append(
            {
                "claim_id": "h1c2",
                "kind": "qualitative",
                "evidence_ids": [],
                "text": "the line stop is consistent with the fault",
            }
        )
        return {
            "incident_id": "x",
            "status": "verified",
            "hypotheses": [
                {
                    "cause_class": cls,
                    "asset_id": asset,
                    "confidence": round(0.5 + _h(sid + "c", 40) / 100, 2),
                    "causal_chain": [asset],
                    "claims": claims,
                    "refuting_evidence_ids": [],
                }
            ],
        }


def _pad_drafts(fixture_dir: Path, n: int = 3) -> None:
    """The template records two judge drafts; a verifier loop may need three (the cap)."""
    f = fixture_dir / "generate_RCAReport.json"
    items = json.loads(f.read_text())
    while len(items) < n:
        items.append(items[-1])
    f.write_text(json.dumps(items, indent=1))
