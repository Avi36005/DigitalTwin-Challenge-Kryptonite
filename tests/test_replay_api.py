"""Replay/API invariants using synthetic participants (no dataset download or credentials needed)."""

import subprocess

import numpy as np
import pytest
from glucotwin.config import paths

API = "/api/v1"


def _session(client, pid="SYN-B", **kw):
    r = client.post(f"{API}/replay/sessions", json={"patient_id": pid, "mode": "synthetic_demo", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _ctl(client, sid, **cmd):
    r = client.post(f"{API}/replay/sessions/{sid}/control", json=cmd)
    assert r.status_code == 200, r.text
    return r.json()


def _all_forecasts(client, sid):
    items, cursor = [], None
    while True:
        params = {"limit": 500, **({"cursor": cursor} if cursor else {})}
        page = client.get(f"{API}/replay/sessions/{sid}/forecasts", params=params).json()
        items += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            return items


def _content(f):
    return (f["as_of"], [(e["horizon_minutes"], e["predicted_mg_dl"], e["lower_mg_dl"], e["upper_mg_dl"],
                          e["components"]) for e in f["estimates"]],
            [(r["score"], r["state"], r["alert_fired"]) for r in f["event_risk"]], f["quality"]["status"],
            f["personalization"]["status"], f["episode_state"])


def test_synthetic_demo_runs_without_dataset(synthetic_ready, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from glucotwin_api.app import create_app

    monkeypatch.setenv("GLUCOTWIN_PROCESSED_DIR", str(tmp_path / "no-dataset"))
    monkeypatch.setenv("GLUCOTWIN_VAR_DIR", str(tmp_path / "var"))
    c = TestClient(create_app())
    ready = c.get(f"{API}/health/ready").json()
    assert ready["synthetic"]["ready"] and not ready["dataset"]["ready"]
    pts = c.get(f"{API}/patients").json()
    assert pts["total"] > 0 and all(p["mode"] == "synthetic_demo" for p in pts["items"])
    s = _session(c, "SYN-A")
    _ctl(c, s["id"], action="step", steps=30)
    f = c.get(f"{API}/replay/sessions/{s['id']}/forecast").json()
    assert f["availability"] == "available"
    assert f["forecast"]["model_version"].startswith("synthetic-demo")
    assert f["forecast"]["mode"] == "synthetic_demo"


def test_forward_replay_equals_reset_and_seek(client):
    a = _session(client)
    for _ in range(10):
        _ctl(client, a["id"], action="step", steps=12)
    clock = client.get(f"{API}/replay/sessions/{a['id']}").json()["clock_at"]
    b = _session(client)
    _ctl(client, b["id"], action="seek", seek_to=clock)
    fa, fb = _all_forecasts(client, a["id"]), _all_forecasts(client, b["id"])
    assert len(fa) == len(fb) > 50
    assert [_content(x) for x in fa] == [_content(x) for x in fb]
    # reset then replay to the same clock in the SAME session reproduces the same content again
    _ctl(client, a["id"], action="reset")
    _ctl(client, a["id"], action="seek", seek_to=clock)
    assert [_content(x) for x in _all_forecasts(client, a["id"])] == [_content(x) for x in fa]


def test_seek_backward_removes_future_state_and_invalidates_cursors(client):
    s = _session(client)
    _ctl(client, s["id"], action="step", steps=288)
    ev = client.get(f"{API}/replay/sessions/{s['id']}/events", params={"limit": 50}).json()
    old_cursor = ev["next_cursor"]
    late = client.get(f"{API}/replay/sessions/{s['id']}").json()
    back = _ctl(client, s["id"], action="seek", seek_to="2000-01-03T08:00:00Z")
    assert back["revision"] == late["revision"] + 1 and back["clock_at"] < late["clock_at"]
    for f in _all_forecasts(client, s["id"]):
        assert f["as_of"] <= back["clock_at"] and f["session_revision"] == back["revision"]
    for a in client.get(f"{API}/replay/sessions/{s['id']}/alerts").json()["items"]:
        assert a["issued_at"] <= back["clock_at"]
    stale = client.get(f"{API}/replay/sessions/{s['id']}/events", params={"cursor": old_cursor})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_cursor"
    twin = client.get(f"{API}/replay/sessions/{s['id']}/twin").json()
    assert twin["as_of"] == back["clock_at"]
    latest = twin["history"]["latest_glucose"]
    assert latest is None or latest["available_at"] <= back["clock_at"]


def test_event_polling_has_no_duplicates_or_gaps_and_respects_availability(client):
    s = _session(client, "SYN-C")  # meals logged 90 minutes late
    _ctl(client, s["id"], action="step", steps=200)
    sess = client.get(f"{API}/replay/sessions/{s['id']}").json()
    seen, cursor = [], None
    while True:
        page = client.get(f"{API}/replay/sessions/{s['id']}/events",
                          params={"limit": 37, **({"cursor": cursor} if cursor else {})}).json()
        seen += page["items"]
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    ids = [e["event_id"] for e in seen]
    assert len(ids) == len(set(ids)) == sess["released_event_count"]
    assert all(e["available_at"] <= sess["clock_at"] for e in seen)
    meals = [e for e in seen if e["kind"] == "meal"]
    assert meals and all(e["available_at"] > e["observed_at"] for e in meals)


def test_sessions_are_isolated(client):
    a, b = _session(client), _session(client)
    _ctl(client, a["id"], action="step", steps=150)
    _ctl(client, b["id"], action="step", steps=20)
    fa = client.get(f"{API}/replay/sessions/{a['id']}/forecast").json()
    fb = client.get(f"{API}/replay/sessions/{b['id']}/forecast").json()
    assert fa["forecast"]["as_of"] > fb["forecast"]["as_of"]
    assert fa["forecast"]["session_id"] == a["id"] and fb["forecast"]["session_id"] == b["id"]
    assert len(_all_forecasts(client, b["id"])) < len(_all_forecasts(client, a["id"]))


def test_insufficient_history_abstains_with_nulls(client):
    s = _session(client, "SYN-E")
    _ctl(client, s["id"], action="step", steps=6)
    f = client.get(f"{API}/replay/sessions/{s['id']}/forecast").json()
    fc = f["forecast"]
    assert fc["quality"]["status"] == "insufficient"
    assert all(e["predicted_mg_dl"] is None and e["lower_mg_dl"] is None for e in fc["estimates"])
    assert all(r["probability"] is None and r["state"] == "insufficient" for r in fc["event_risk"])


def test_null_intervals_when_not_calibrated(synthetic_ready):
    from glucotwin.data.pipeline import synthetic_store_dir
    from glucotwin.data.store import Store
    from glucotwin.events import EventDefinition
    from glucotwin.serving import load_serving
    from glucotwin.twin import TwinEngine

    serving = load_serving("synthetic_demo")
    serving.config = {**serving.config, "intervals": {"quantiles_mg_dl": {}, "level": None}}
    pdata = Store(synthetic_store_dir()).load("SYN-A")
    eng = TwinEngine("t", 1, pdata.meta, serving, EventDefinition())
    out = eng.advance(pdata, float(np.max([0])) + 2880 * 1.5 + 3000)
    ok = [f for f in out if f["quality"]["status"] != "insufficient"]
    assert ok
    for f in ok:
        for e in f["estimates"]:
            assert e["predicted_mg_dl"] is not None
            assert e["lower_mg_dl"] is None and e["upper_mg_dl"] is None and e["interval_level"] is None
            assert e["interval_status"] == "unavailable"


def test_alert_acknowledgement_is_local_and_idempotent(client):
    s = _session(client, "SYN-B")
    _ctl(client, s["id"], action="step", steps=600)
    alerts = client.get(f"{API}/replay/sessions/{s['id']}/alerts").json()
    assert alerts["rule_available"] and alerts["items"], "expected research warnings for SYN-B"
    a = alerts["items"][0]
    assert a["evidence"]["score_kind"] == "forecast_margin_mg_dl"
    r1 = client.post(f"{API}/replay/sessions/{s['id']}/alerts/{a['alert_id']}/acknowledgement", json={"note": "seen"})
    r2 = client.post(f"{API}/replay/sessions/{s['id']}/alerts/{a['alert_id']}/acknowledgement", json={})
    assert r1.status_code == r2.status_code == 200
    ack1, ack2 = r1.json()["acknowledgement"], r2.json()["acknowledgement"]
    assert ack1["acknowledged"] and ack1 == ack2
    assert "No message was sent" in ack1["meaning"]


def test_malformed_and_unknown_requests_use_error_envelope(client):
    s = _session(client)
    r = client.post(f"{API}/replay/sessions/{s['id']}/control", json={"action": "seek"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.post(f"{API}/replay/sessions/{s['id']}/control", json={"action": "jump"})
    assert r.status_code == 422
    r = client.get(f"{API}/replay/sessions/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"
    r = client.post(f"{API}/replay/sessions/{s['id']}/control",
                    json={"action": "seek", "seek_to": "1999-01-01T00:00:00Z"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "time_out_of_bounds"


def test_offline_features_match_online_engine(synthetic_ready):
    """The evaluated transformation is the served transformation (population predictions agree)."""
    from glucotwin.data.pipeline import synthetic_store_dir
    from glucotwin.data.store import Store
    from glucotwin.events import EventDefinition
    from glucotwin.features import build_features, prepare
    from glucotwin.serving import load_serving
    from glucotwin.twin import TwinEngine

    serving = load_serving("synthetic_demo")
    pdata = Store(synthetic_store_dir()).load("SYN-D")
    prep = prepare(pdata)
    origins = np.unique(prep.g_avail)
    offline = serving.predict(build_features(prep, origins, serving.spec).frame)
    eng = TwinEngine("p", 1, pdata.meta, serving, EventDefinition())
    online = []
    # advance in irregular chunks using only released data, like the replay service does
    from glucotwin_api.catalog import Catalog

    tl = Catalog().timeline("SYN-D")
    for clock in np.linspace(tl.start, tl.end, 37)[1:]:
        online += eng.advance(tl.released(clock), clock)
    assert [f["_origin"] for f in online] == origins.tolist()
    q = [f["quality"]["status"] for f in online]
    for h_idx, h in enumerate(serving.horizons):
        on = np.array([f["estimates"][h_idx]["components"]["population_mg_dl"] if f["estimates"][h_idx]["components"]
                       else np.nan for f in online], dtype=float)
        mask = np.array([s != "insufficient" for s in q])
        assert np.allclose(on[mask], np.round(offline[h][mask], 1), atol=0.051)


def test_patient_level_data_and_private_notes_are_git_ignored():
    root = paths().root
    probes = ["data/raw/cgmacros/1.0.0/tables/CGMacros-001.csv", "data/processed/cgmacros/v1/catalog.sqlite",
              "data/private/cgmacros_pseudonym_map.json", "context.md", "var/glucotwin.sqlite3"]
    try:
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True,
                                text=True, check=False).stdout.strip()
    except FileNotFoundError:
        pytest.skip("git not available")
    if inside != "true":
        pytest.skip("not a git work tree (e.g. an exported copy)")
    out = subprocess.run(["git", "check-ignore", *probes], cwd=root, capture_output=True, text=True, check=False)
    assert sorted(out.stdout.split()) == sorted(probes)
    tracked = subprocess.run(["git", "ls-files", "data/raw", "data/processed", "data/private"], cwd=root,
                             capture_output=True, text=True, check=False).stdout.strip()
    assert tracked == ""


def test_license_and_provenance_are_present():
    root = paths().root
    assert (root / "LICENSE").exists()
    prov = root / "data/processed/cgmacros/v1/provenance.json"
    if not prov.exists():
        pytest.skip("CGMacros not imported on this machine")
    import json

    p = json.loads(prov.read_text())
    assert p["license"] == "CC BY-NC-SA 4.0" and all(f["verified"] for f in p["files"])


# ------------------------------------------------------------------------------------------------ evidence catalogue


def test_participant_filters_are_server_side_and_total_counts_every_match(client):
    allp = client.get("/api/v1/patients", params={"limit": 200}).json()
    syn = client.get("/api/v1/patients", params={"mode": "synthetic_demo", "limit": 3}).json()
    assert syn["total"] == sum(1 for p in allp["items"] if p["mode"] == "synthetic_demo")
    assert len(syn["items"]) <= 3 and syn["total_unfiltered"] == allp["total"]
    if syn["total"] > 3:
        nxt = client.get("/api/v1/patients", params={"mode": "synthetic_demo", "limit": 3,
                                                       "cursor": syn["next_cursor"]}).json()
        assert not {p["patient_id"] for p in nxt["items"]} & {p["patient_id"] for p in syn["items"]}
    q = client.get("/api/v1/patients", params={"q": "SYN-T0", "sort": "recording_days", "order": "desc"}).json()
    days = [p["coverage"]["recording_days"] for p in q["items"] if p["coverage"]["recording_days"] is not None]
    assert days == sorted(days, reverse=True) and all("SYN-T0" in p["patient_id"] for p in q["items"])


def test_serving_model_is_reported_independently_of_any_research_report(client):
    s = client.get("/api/v1/serving").json()
    modes = {x["mode"]: x for x in s["items"]}
    assert set(modes) == {"dataset_replay", "synthetic_demo"}
    ev = client.get("/api/v1/evaluations").json()
    assert sum(1 for x in ev["items"] if x["is_serving_evidence"]) <= 1
    assert all(x["regime"] in ("serving_retrospective", "superseded_serving", "superseded_original", "nested_research")
               for x in ev["items"])
    # only the experiment behind the serving model is labelled serving evidence
    assert all((x["regime"] == "serving_retrospective") == x["is_serving_evidence"] for x in ev["items"]
               if x["regime"] != "nested_research")


def test_unknown_research_experiment_and_inventory_shapes(client):
    assert client.get("/api/v1/research/not-an-experiment").status_code == 404
    inv = client.get("/api/v1/datasets").json()
    assert inv["status"] in ("available", "not_generated")
    for d in inv.get("datasets", []):
        # imported != trained on: the inventory never claims assessment without the research report
        assert d["access_status"] in ("planned", "access_required", "available_locally", "imported",
                                      "failed_validation", "eligible_for_experiment")
