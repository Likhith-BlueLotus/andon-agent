"""Offline tests for simulator text generation: mocked Gemini, validation, caching, WO history."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np

import config
from agents.llm import LLM
from simulator import text_artifacts as ta
from simulator.text_artifacts import NoteSlot, TextGen


def _resp(payload: dict, prompt_tokens: int = 900, out_tokens: int = 200):
    return SimpleNamespace(
        text=json.dumps(payload),
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=out_tokens,
            cached_content_token_count=0,
            thoughts_token_count=0,
        ),
    )


def _slots() -> list[NoteSlot]:
    t = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    return [
        NoteSlot(1, t, "line_lead", "english", ["no major alarms in previous shift"]),
        NoteSlot(2, t + timedelta(hours=2), "maintenance_tech", "hinglish",
                 ["16:30 line stopped: ST60 Vision check quality stop", "maintenance called"]),
    ]  # fmt: skip


def test_shift_notes_live_then_cached_and_validated(tmp_path):
    calls: list[tuple[str, str]] = []

    async def transport(model_id, contents, gen_config):
        calls.append((model_id, contents))
        return _resp({"notes": [
            {"slot": 1, "text": "shift ok, no big alarms"},
            {"slot": 2, "text": "ST60 pe quality stop, lagta hai tip wear hai"},  # names a cause -> rejected
        ]})  # fmt: skip

    gen = TextGen(mode="live", llm=LLM(transport=transport), cache_dir=tmp_path)
    notes = gen.run(ta.shift_notes("S999", _slots(), gen, np.random.default_rng(0)))
    assert [n.note_id for n in notes] == ["S999-N01", "S999-N02"]
    assert notes[0].text == "shift ok, no big alarms"
    assert "tip wear" not in notes[1].text and "line stopped" in notes[1].text  # template fallback
    assert calls and calls[0][0] == config.FLASH_LITE
    prompt = calls[0][1]
    assert "<slots>" in prompt and "never guess" in prompt.lower()
    for word in ("weld_tip_wear", "root_cause", "truth"):
        assert word not in prompt
    assert gen.usd > 0 and gen.calls == 1

    gen2 = TextGen(mode="live", llm=LLM(transport=transport), cache_dir=tmp_path)
    again = gen2.run(ta.shift_notes("S999", _slots(), gen2, np.random.default_rng(0)))
    assert [n.text for n in again] == [n.text for n in notes]
    assert gen2.calls == 0 and gen2.cache_hits == 1 and gen2.usd == 0
    assert len(calls) == 1


def test_parse_failure_retries_once_then_templates(tmp_path):
    n = {"calls": 0}

    async def transport(model_id, contents, gen_config):
        n["calls"] += 1
        return SimpleNamespace(text="not json", usage_metadata=None)

    gen = TextGen(mode="live", llm=LLM(transport=transport), cache_dir=tmp_path)
    notes = gen.run(ta.shift_notes("S998", _slots(), gen, np.random.default_rng(1)))
    assert n["calls"] == 2 and len(notes) == 2 and gen.failures
    assert not list(tmp_path.rglob("*.json"))


def test_cached_mode_never_calls_the_llm(tmp_path):
    async def transport(*_a):  # pragma: no cover - must not be called
        raise AssertionError("LLM called in cached mode")

    gen = TextGen(mode="cached", llm=LLM(transport=transport), cache_dir=tmp_path)
    notes = gen.run(ta.shift_notes("S997", _slots(), gen, np.random.default_rng(2)))
    assert len(notes) == 2 and gen.misses_templated == 1


def test_work_order_skeleton_wrong_first_pairs():
    rows = ta.wo_skeleton(2000, 2026)
    assert len(rows) == 2000 and len({r["wo_id"] for r in rows}) == 2000
    wrong = [r for r in rows if r["kind"] == "wrong_first"]
    corr = {r["wo_id"]: r for r in rows if r["kind"] == "correction"}
    assert len(wrong) == len(corr) == 100  # 5 % wrong first diagnoses, each corrected later
    for w in wrong:
        c = corr[w["corrected_by"]]
        assert c["ref"] == w["wo_id"] and c["asset_id"] == w["asset_id"] and c["date"] > w["date"]
        assert w["theme"] != c["theme"] and c["cause"] is not None
    assert all(ta.WO_START <= r["date"] <= ta.WO_END + timedelta(days=11) for r in rows)
    assert ta.wo_skeleton(2000, 2026) == rows


def test_work_orders_mocked_llm_uses_style_examples_as_untrusted(tmp_path):
    seen: list[str] = []

    async def transport(model_id, contents, gen_config):
        seen.append(contents)
        rows = json.loads(contents.split("<rows>")[1].split("</rows>")[0])
        return _resp(
            {
                "rows": [
                    {
                        "row": r["row"],
                        "symptom": "chk noise",
                        "action": "repl part",
                        "outcome": "ok",
                    }
                    for r in rows
                ]
            }
        )

    maintie = tmp_path / "maintie"
    maintie.mkdir()
    (maintie / "gold_release.json").write_text(
        json.dumps([{"text": f"<id> pump {i} not working"} for i in range(40)])
    )
    gen = TextGen(mode="live", llm=LLM(transport=transport), cache_dir=tmp_path / "cache")
    wos, labels = gen.run(ta.build_work_orders(gen, 120, 5, maintie, batch=50))
    assert len(wos) == 120 and len(seen) == 3
    assert all(w["symptom"] == "chk noise" for w in wos)
    assert "<style_examples>" in seen[0] and "untrusted" in seen[0] and "not working" in seen[0]
    assert {lb["text_source"] for lb in labels} == {"llm"}
    assert set(wos[0]) == {
        "wo_id",
        "date",
        "asset_id",
        "symptom",
        "action",
        "outcome",
        "technician_role",
    }


def test_banned_terms_catch_cause_names():
    assert ta.banned_hits("air leak near ST20") == ["leak"]
    assert ta.banned_hits("ST60 rejects high, QA informed") == []
