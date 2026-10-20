"""Saved research summaries are read whole or reported for what they are: not run, malformed or incompatible — never a
half-read result, and never "not run" when a file exists. Verdicts say whether a protocol declared the rule.
Also: the public-demo restrictions never remove evidence from a local (recorded-data) installation."""

import json

import pytest
from glucotwin.config import paths
from glucotwin_api.evidence import BASIS, read_summary

EXT = "gt-2h-ext-2026-10-20"
WARN = "gt-warn-range-2026-10-20"


def _ext(eid=EXT):
    c = {"mean_diff": -2.12, "ci95": [-2.67, -1.53], "improved": 78, "n": 98}
    return {"experiment_id": eid, "participants": 98, "opened": {"opened_at": "2026-10-20T10:10:25+00:00", "reopened": []},
            "mae": {"120": 29.553}, "persistence_mae": {"120": 31.675}, "minus_persistence": {"120": c}}


def _warn(before=0.70, after=0.75):
    r = lambda cov: {"60": {"coverage_pooled": cov, "width_mean": 60.0},  # noqa: E731
                     "120": {"coverage_pooled": cov, "width_mean": 90.0}}
    prior = {"c1_minus_population": {"mean_diff": -0.5, "ci95": [-1.5, 0.5], "better_for": 10, "n_participants": 14}}
    return {"opened": {"opened_at": "2026-10-20T12:24:25+00:00", "protocol": WARN, "reopened": []},
            "ranges": {"B0_calibration": r(before), "B1_pooled": r(after)},
            "warnings": {"selected": {"early": 126, "lead_median": 15.0}, "incumbent": {"early": 123, "onsets": 329}},
            "warning_diff_selected_minus_incumbent": {"early_share_diff": 0.009, "early_share_ci95": [-0.055, 0.066],
                                                      "people": 14},
            "profile_prior": {"all": {"120": prior}, "first_24h": {"120": prior}}}


def test_absent_is_not_run(tmp_path):
    assert read_summary("D-045", EXT, tmp_path / "missing.json")["status"] == "not_run"


def test_unparseable_or_non_object_is_malformed_not_not_run(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    out = read_summary("D-045", EXT, p)
    assert out["status"] == "malformed" and "could not be read" in out["status_detail"]
    p.write_text("[1, 2]")
    assert read_summary("D-045", EXT, p)["status"] == "malformed"


def test_other_experiment_or_missing_fields_is_incompatible(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_ext("gt-2h-clf-2026-10-20")))
    out = read_summary("D-045", EXT, p)
    assert out["status"] == "incompatible" and "belongs to gt-2h-clf-2026-10-20" in out["status_detail"]
    s = _ext()
    del s["minus_persistence"]
    p.write_text(json.dumps(s))
    assert read_summary("D-045", EXT, p)["status"] == "incompatible"
    assert "findings" not in read_summary("D-045", EXT, p)  # never half-read


def test_valid_summary_is_available_with_its_verdict_basis(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_ext()))
    out = read_summary("D-045", EXT, p)
    assert out["status"] == "available" and out["participants"] == 98
    (f,) = out["findings"]
    assert f["verdict"] == "shown" and f["basis"] == "display_heuristic"


def test_ranges_verdict_is_a_description_not_a_one_point_bar(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_warn(before=0.70, after=0.75)))  # closer to 80 %, still 5 points short
    out = read_summary("D-046", WARN, p)
    ranges = next(f for f in out["findings"] if f["key"] == "ranges_120")
    assert ranges["verdict"] == "shown" and ranges["basis"] == "display_heuristic"
    assert "not a pass bar" in ranges["basis_note"]
    p.write_text(json.dumps(_warn(before=0.79, after=0.70)))  # moved away from the target
    ranges = next(f for f in read_summary("D-046", WARN, p)["findings"] if f["key"] == "ranges_120")
    assert ranges["verdict"] == "not_shown"
    prior = next(f for f in read_summary("D-046", WARN, p)["findings"] if f["key"] == "profile_prior_120")
    assert prior["basis"] == "declared_rule"


def test_only_d046_part_c_is_a_declared_rule():
    assert [k for k, (b, _) in BASIS.items() if b == "declared_rule"] == ["profile_prior_120"]


@pytest.mark.skipif(not (paths().artifacts / "experiments" / "gt-primary-2026-10-13-fusion" / "metrics.json").exists(),
                    reason="needs the saved CGMacros evaluation (git-ignored artifacts)")
def test_local_installation_keeps_all_evidence(tmp_path, monkeypatch):
    """Public mode strips per-participant rows and identifiers; a local install must still get them, read from the
    saved artifacts, never from the published snapshot."""
    from fastapi.testclient import TestClient
    from glucotwin_api.app import create_app

    monkeypatch.setenv("GLUCOTWIN_VAR_DIR", str(tmp_path / "var"))
    monkeypatch.delenv("GLUCOTWIN_PUBLIC_DEMO", raising=False)
    c = TestClient(create_app())
    ev = c.get("/api/v1/evaluations/latest").json()
    assert ev["status"] == "completed" and ev.get("source") is None
    assert len(ev["per_patient"]) > 0
    assert any(x.get("display_alias") for x in ev["cohort"]["excluded"])
    assert c.get("/api/v1/patients", params={"mode": "dataset_replay"}).status_code == 200
    rs = c.get("/api/v1/research-summaries").json()
    assert rs.get("source") is None
    assert all(it["status"] in ("available", "not_run") for it in rs["items"])
    research = c.get("/api/v1/research/gt-nested-2026-10-12-v1")
    if research.status_code == 200 and research.json().get("status") == "completed":
        assert "pt-" in research.text  # pseudonymous calibration participants stay visible locally
