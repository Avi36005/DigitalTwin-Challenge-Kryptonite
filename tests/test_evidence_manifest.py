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
    bad = [(r["id"], c) for r in rows for c in r["checks"] if c["result"] != "matches"]
    assert bad == []
    assert {r["status"] for r in rows} <= {"matches artifact", "author-reported"}


@pytest.mark.skipif(not HAVE, reason="needs the saved CGMacros evaluation (git-ignored artifacts)")
def test_a_changed_readme_number_is_a_mismatch():
    text = (ROOT / "README.md").read_text().replace("MAE **12.96 / 20.26**", "MAE **12.50 / 20.26**", 1)
    rows = em.evaluate(text)
    demo = next(r for r in rows if r["id"] == "demo-forecast")
    assert demo["status"] == "MISMATCH"
    assert next(c for c in demo["checks"] if c["label"] == "MAE 30") == {
        "label": "MAE 30", "artifact": "12.96", "readme": "12.50", "result": "MISMATCH"}
