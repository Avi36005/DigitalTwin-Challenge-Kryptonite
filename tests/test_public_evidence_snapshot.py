"""Published evidence snapshot (reports/public_evidence/): served only in public demonstration mode and only when the
saved artifacts are missing; the export refuses anything that names or lists a participant."""

import json

import pytest

API = "/api/v1"
NOT_RUN = {"schema_version": "1.0", "status": "not_run", "status_message": "No completed real-data evaluation."}


def _snapshot(tmp_path):
    d = tmp_path / "public_evidence"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"exported_at": "2026-10-20T14:56:20+00:00", "commit": "abc123def456",
                                                 "files": ["evaluations__latest.json", "datasets.json"]}))
    (d / "evaluations__latest.json").write_text(json.dumps({**NOT_RUN, "status": "completed",
                                                            "status_message": "Published evidence."}))
    (d / "datasets.json").write_text(json.dumps({"schema_version": "1.0", "status": "available", "datasets": []}))
    return d


def _client(monkeypatch, tmp_path, public):
    from fastapi.testclient import TestClient
    from glucotwin_api import app as app_mod
    from glucotwin_api import evidence, snapshot

    monkeypatch.setenv("GLUCOTWIN_VAR_DIR", str(tmp_path / "var"))
    if public:
        monkeypatch.setenv("GLUCOTWIN_PUBLIC_DEMO", "1")
    else:
        monkeypatch.delenv("GLUCOTWIN_PUBLIC_DEMO", raising=False)
    d = _snapshot(tmp_path)
    monkeypatch.setattr(snapshot, "directory", lambda: d)
    # an installation without saved artifacts (the container)
    monkeypatch.setattr(app_mod, "build_report", lambda *a, **k: dict(NOT_RUN))
    monkeypatch.setattr(evidence, "dataset_inventory", lambda: {"schema_version": "1.0", "status": "not_generated"})
    return TestClient(app_mod.create_app())


def test_public_demo_serves_the_snapshot_when_artifacts_are_missing(synthetic_ready, tmp_path, monkeypatch):
    c = _client(monkeypatch, tmp_path, public=True)
    r = c.get(f"{API}/evaluations/latest").json()
    assert r["status"] == "completed" and r["source"] == "published_snapshot"
    assert r["snapshot_commit"] == "abc123def456" and r["snapshot_exported_at"].startswith("2026-10-20")
    d = c.get(f"{API}/datasets").json()
    assert d["status"] == "available" and d["source"] == "published_snapshot"
    # an evaluation with no snapshot file stays an honest 404
    assert c.get(f"{API}/evaluations/gt-unknown").status_code == 404


def test_local_mode_never_reads_the_snapshot(synthetic_ready, tmp_path, monkeypatch):
    c = _client(monkeypatch, tmp_path, public=False)
    r = c.get(f"{API}/evaluations/latest").json()
    assert r["status"] == "not_run" and r.get("source") is None
    assert c.get(f"{API}/datasets").json()["status"] == "not_generated"


def test_guard_refuses_identifiers_and_participant_rows():
    from glucotwin_api.snapshot import SnapshotLeak, check_aggregate

    for bad in ({"note": "calibrated on pt-506d88"}, {"per_patient": [{"mae": 1.0}]},
                {"cohort": {"excluded": [{"display_alias": "Participant 15"}]}}, {"patient_id": "SYN-B"},
                {"rows": [{"participant": "x", "mae": 2.0}]}, {"pt-1eef47": 3}):
        with pytest.raises(SnapshotLeak):
            check_aggregate(bad)
    check_aggregate({"per_patient": [], "per_patient_coverage_min": 0.6, "participants_included": 14,
                     "folds": [{"assessment": 3, "calibration": 2}], "cohort": {"excluded": [{"reason": "Pre-diabetes"}]}})


def test_withhold_ids_turns_identifier_lists_into_counts():
    from glucotwin_api.snapshot import withhold_ids

    out = withhold_ids({"intervals": {"calibration_participants": ["pt-506d88", "pt-1eef47"], "level": 0.8},
                        "labels": ["a", "b"], "folds": [{"assessment": ["pt-3e3236"]}]})
    assert out == {"intervals": {"calibration_participants": 2, "level": 0.8}, "labels": ["a", "b"],
                   "folds": [{"assessment": 1}]}


def test_committed_snapshot_is_aggregate_only():
    from glucotwin.config import paths
    from glucotwin_api.snapshot import check_aggregate

    d = paths().reports / "public_evidence"
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        pytest.skip("no published snapshot in this checkout")
    for f in files:
        check_aggregate(json.loads(f.read_text()), f.name)
