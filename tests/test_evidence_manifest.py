"""The evidence manifest re-derives each README number from its saved artifact and catches a changed number."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("evidence_manifest", ROOT / "scripts" / "evidence_manifest.py")
em = importlib.util.module_from_spec(spec)
spec.loader.exec_module(em)

HAVE = (ROOT / "artifacts" / "experiments" / "gt-primary-2026-10-13-fusion" / "metrics.json").exists()


def test_numbers_are_written_the_way_the_readme_writes_them():
    assert em.sgn(-0.5321, 2) == "−0.53" and em.sgn(0.582, 2) == "+0.58"
    assert em.pct(0.7981) == "79.8" and em.num(12.957, 2) == "12.96"


@pytest.mark.skipif(not HAVE, reason="needs the saved CGMacros evaluation (git-ignored artifacts)")
def test_readme_matches_every_saved_artifact():
    rows = em.evaluate((ROOT / "README.md").read_text())
    settled = [r for r in rows if not r.get("pending_readme")]
    bad = [(r["id"], c) for r in settled for c in r["checks"] if c["result"] != "matches"]
    assert bad == []
    assert {r["status"] for r in settled} <= {"matches artifact", "author-reported"}
    # a study whose README wording is not written yet may be pending, never contradicted
    assert all(r["status"] != "MISMATCH" for r in rows if r.get("pending_readme"))


@pytest.mark.skipif(not HAVE, reason="needs the saved CGMacros evaluation (git-ignored artifacts)")
def test_a_changed_readme_number_is_a_mismatch():
    text = (ROOT / "README.md").read_text().replace("MAE **12.96 / 20.26**", "MAE **12.50 / 20.26**", 1)
    rows = em.evaluate(text)
    demo = next(r for r in rows if r["id"] == "demo-forecast")
    assert demo["status"] == "MISMATCH"
    assert next(c for c in demo["checks"] if c["label"] == "MAE 30") == {
        "label": "MAE 30", "artifact": "12.96", "readme": "12.50", "result": "MISMATCH"}


def test_artifact_paths_and_hashes(tmp_path):
    assert em.artifact_paths("a/b.json; c/d.parquet (via scripts/x.py)") == ["a/b.json", "c/d.parquet"]
    assert em.sha256_of("no/such/file.json") is None
    assert em.sha256_of("README.md") == __import__("hashlib").sha256((ROOT / "README.md").read_bytes()).hexdigest()


def test_every_row_records_its_artifact_hashes():
    rows = em.evaluate((ROOT / "README.md").read_text())
    for r in rows:
        assert set(r["artifact_sha256"]) == set(em.artifact_paths(r["artifact"]))


def test_d052_rows_are_pending_until_the_readme_sentence_exists():
    rows = {r["id"]: r for r in em.evaluate("no study sentence here")}
    for rid in ("joint-d052-forecast", "joint-d052-operational"):
        assert rows[rid]["pending_readme"] is True
        assert rows[rid]["status"] in {"artifact missing", "not found in README"}


@pytest.mark.skipif(not (ROOT / "artifacts/research/gt-joint-2026-10-21/summary.json").exists(),
                    reason="D-052 summary not saved on this installation")
def test_d052_sentence_from_the_saved_summary_matches_its_checks():
    rows = {r["id"]: r for r in em.evaluate((ROOT / "README.md").read_text() + "\n\n" + em.readme_sentence_d052())}
    for rid in ("joint-d052-forecast", "joint-d052-operational"):
        assert rows[rid]["status"] == "matches artifact", rows[rid]["checks"]


@pytest.mark.parametrize("passed,diff,ci", [(True, -0.71, [-1.10, -0.30]), (False, 0.12, [-0.40, 0.65])])
def test_d052_patterns_round_trip_on_a_made_up_summary(monkeypatch, passed, diff, ci):
    fake = {"procedures": {"S": {"60": {"mae": 21.8412}}, "R0": {"60": {"mae": 22.5482}}},
            "gate": {"mean_diff_60": diff, "ci95_60": ci, "passed": passed},
            "release_guardrails": {"passed": not passed}, "ranges": {"S": {"60": {"coverage": 0.7934}}}}
    monkeypatch.setattr(em, "joint", lambda: fake)
    rows = {r["id"]: r for r in em.evaluate("Joint selection: " + em.readme_sentence_d052())}
    for rid in ("joint-d052-forecast", "joint-d052-operational"):
        assert rows[rid]["status"] == "matches artifact", rows[rid]["checks"]
    # a changed number in the sentence is caught
    wrong = em.readme_sentence_d052().replace("21.84", "21.50")
    assert {r["id"]: r for r in em.evaluate(wrong)}["joint-d052-forecast"]["status"] == "MISMATCH"
