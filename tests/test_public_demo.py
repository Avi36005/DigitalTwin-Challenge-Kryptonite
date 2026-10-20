"""Public synthetic demonstration mode (GLUCOTWIN_PUBLIC_DEMO=1): off by default, synthetic only, sessions private to
each visitor, capped, expiring and rate-limited; the built web app served from the same process."""

import pytest

API = "/api/v1"


def _app(monkeypatch, tmp_path, public=True, **env):
    from fastapi.testclient import TestClient  # noqa: F401  (import check)
    from glucotwin_api.app import create_app

    monkeypatch.setenv("GLUCOTWIN_VAR_DIR", str(tmp_path / "var"))
    if public:
        monkeypatch.setenv("GLUCOTWIN_PUBLIC_DEMO", "1")
    else:
        monkeypatch.delenv("GLUCOTWIN_PUBLIC_DEMO", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return create_app()


def _client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _session(c, pid="SYN-B"):
    r = c.post(f"{API}/replay/sessions", json={"patient_id": pid, "mode": "synthetic_demo"})
    assert r.status_code == 201, r.text
    return r.json()


def test_off_by_default(synthetic_ready, tmp_path, monkeypatch):
    c = _client(_app(monkeypatch, tmp_path, public=False))
    h = c.get(f"{API}/health").json()
    assert h["public_demo"] is False and h["public_demo_limits"] is None
    r = c.get(f"{API}/patients", params={"mode": "dataset_replay"})
    assert r.status_code == 200
    assert "gt_visitor" not in c.cookies
    a = _session(c)
    other = _client(c.app)  # locally every client sees every session, as before
    assert other.get(f"{API}/replay/sessions/{a['id']}").status_code == 200
    assert a["id"] in [s["id"] for s in other.get(f"{API}/replay/sessions").json()["items"]]


def test_health_and_cookie(synthetic_ready, tmp_path, monkeypatch):
    c = _client(_app(monkeypatch, tmp_path))
    r = c.get(f"{API}/health")
    h = r.json()
    assert h["public_demo"] is True
    assert h["public_demo_limits"] == {"session_idle_minutes": 120, "max_sessions_per_visitor": 5}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("gt_visitor=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie and "Max-Age=604800" in cookie and "Secure" not in cookie
    assert "set-cookie" not in c.get(f"{API}/health").headers  # a valid cookie is kept, not replaced
    c2 = _client(_app(monkeypatch, tmp_path, GLUCOTWIN_COOKIE_SECURE=1))
    assert "Secure" in c2.get(f"{API}/health").headers["set-cookie"]


def test_visitors_cannot_see_or_drive_each_others_sessions(synthetic_ready, tmp_path, monkeypatch):
    app = _app(monkeypatch, tmp_path)
    a, b = _client(app), _client(app)
    a.get(f"{API}/health"), b.get(f"{API}/health")
    assert a.cookies["gt_visitor"] != b.cookies["gt_visitor"]
    s = _session(a)
    sid = s["id"]
    assert a.post(f"{API}/replay/sessions/{sid}/control", json={"action": "step", "steps": 600}).status_code == 200
    alerts = a.get(f"{API}/replay/sessions/{sid}/alerts").json()["items"]
    assert alerts, "expected research warnings for SYN-B"
    aid = alerts[0]["alert_id"]

    assert sid in [x["id"] for x in a.get(f"{API}/replay/sessions").json()["items"]]
    assert b.get(f"{API}/replay/sessions").json()["items"] == []
    for path in ("", "/events", "/profile", "/twin", "/forecast", "/forecasts", "/alerts", "/review-snapshot"):
        r = b.get(f"{API}/replay/sessions/{sid}{path}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found", path
    r = b.post(f"{API}/replay/sessions/{sid}/control", json={"action": "reset"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"
    r = b.post(f"{API}/replay/sessions/{sid}/alerts/{aid}/acknowledgement", json={"note": "not mine"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"
    assert a.get(f"{API}/replay/sessions/{sid}/alerts").json()["items"][0]["acknowledgement"]["acknowledged"] is False
    # an unknown session reads exactly the same
    unknown = b.get(f"{API}/replay/sessions/000000000000").json()["error"]
    assert unknown["code"] == "session_not_found"

    # patients' active_session reflects only the caller's own replay
    pa = {p["patient_id"]: p for p in a.get(f"{API}/patients").json()["items"]}
    pb = {p["patient_id"]: p for p in b.get(f"{API}/patients").json()["items"]}
    assert pa["SYN-B"]["active_session"]["session_id"] == sid
    assert pb["SYN-B"]["active_session"] is None
    assert b.get(f"{API}/patients/SYN-B").json()["active_session"] is None
    # a visitor without any cookie is a new visitor
    fresh = _client(app)
    assert fresh.get(f"{API}/replay/sessions/{sid}").status_code == 404


def test_synthetic_only(synthetic_ready, tmp_path, monkeypatch):
    local = _client(_app(monkeypatch, tmp_path, public=False))
    dataset_ids = [p["patient_id"] for p in
                   local.get(f"{API}/patients", params={"mode": "dataset_replay", "limit": 5}).json()["items"]]
    c = _client(_app(monkeypatch, tmp_path))
    r = c.get(f"{API}/patients", params={"mode": "dataset_replay"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "public_demo_synthetic_only"
    body = c.get(f"{API}/patients").json()
    assert body["total"] > 0 and all(p["mode"] == "synthetic_demo" for p in body["items"])
    assert body["total_unfiltered"] == body["total"]
    r = c.post(f"{API}/replay/sessions", json={"patient_id": dataset_ids[0] if dataset_ids else "SYN-B",
                                               "mode": "dataset_replay"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "public_demo_synthetic_only"
    serving = {s["mode"]: s for s in c.get(f"{API}/serving").json()["items"]}
    assert serving["dataset_replay"]["status"] == "unavailable"
    if dataset_ids:  # only when CGMacros is imported on this machine
        r = c.get(f"{API}/patients/{dataset_ids[0]}")
        assert r.status_code == 403 and r.json()["error"]["code"] == "public_demo_synthetic_only"
        rep = c.get(f"{API}/evaluations/latest").json()
        assert rep["per_patient"] == []
        assert not any("participant" in str(o.get("results", "")) for o in rep["optional_experiments"])


def test_session_cap_evicts_least_recently_used(synthetic_ready, tmp_path, monkeypatch):
    app = _app(monkeypatch, tmp_path)
    mgr = app.state.gt.sessions
    t = [1000.0]
    mgr.now = lambda: t[0]
    c, other = _client(app), _client(app)
    ids = []
    for _ in range(5):
        t[0] += 1
        ids.append(_session(c)["id"])
    t[0] += 1
    c.get(f"{API}/replay/sessions/{ids[0]}")  # touch the oldest: the second-oldest is now least recently used
    t[0] += 1
    keep_other = _session(other)["id"]
    t[0] += 1
    new = _session(c)["id"]
    mine = {x["id"] for x in c.get(f"{API}/replay/sessions").json()["items"]}
    assert len(mine) == 5 and new in mine and ids[0] in mine and ids[1] not in mine
    assert c.get(f"{API}/replay/sessions/{ids[1]}").status_code == 404
    assert other.get(f"{API}/replay/sessions/{keep_other}").status_code == 200  # other visitors untouched


def test_global_cap(synthetic_ready, tmp_path, monkeypatch):
    app = _app(monkeypatch, tmp_path, GLUCOTWIN_PUBLIC_MAX_SESSIONS=3)
    mgr = app.state.gt.sessions
    t = [0.0]
    mgr.now = lambda: t[0]
    clients = [_client(app) for _ in range(4)]
    ids = []
    for c in clients:
        t[0] += 1
        ids.append(_session(c)["id"])
    assert len(mgr.sessions) == 3 and ids[0] not in mgr.sessions
    assert clients[0].get(f"{API}/replay/sessions/{ids[0]}").status_code == 404


def test_idle_sessions_expire(synthetic_ready, tmp_path, monkeypatch):
    app = _app(monkeypatch, tmp_path)
    mgr = app.state.gt.sessions
    t = [0.0]
    mgr.now = lambda: t[0]
    c = _client(app)
    sid = _session(c)["id"]
    t[0] += 119 * 60
    assert c.get(f"{API}/replay/sessions/{sid}").status_code == 200  # use resets the idle clock
    t[0] += 119 * 60
    assert c.get(f"{API}/replay/sessions/{sid}/forecast").status_code == 200
    t[0] += 121 * 60
    r = c.get(f"{API}/replay/sessions/{sid}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"
    assert sid not in mgr.sessions
    sid2 = _session(c)["id"]
    t[0] += 121 * 60
    assert c.get(f"{API}/replay/sessions").json()["items"] == []  # listing sweeps expired sessions too
    assert sid2 not in mgr.sessions


def test_rate_limit(synthetic_ready, tmp_path, monkeypatch):
    app = _app(monkeypatch, tmp_path, GLUCOTWIN_PUBLIC_VISITOR_RPM=5)
    c = _client(app)
    codes = [c.get(f"{API}/health").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    r = c.get(f"{API}/health")
    assert r.json()["error"]["code"] == "rate_limited" and r.headers["Retry-After"] == "60"
    assert r.json()["error"]["request_id"]
    assert _client(app).get(f"{API}/health").status_code == 200  # another visitor has its own allowance
    ip = _client(_app(monkeypatch, tmp_path, GLUCOTWIN_PUBLIC_VISITOR_RPM=100, GLUCOTWIN_PUBLIC_IP_RPM=3))
    assert [ip.get(f"{API}/health").status_code for _ in range(4)] == [200, 200, 200, 429]


def test_forwarded_ip_only_when_trusted(synthetic_ready, tmp_path, monkeypatch):
    app = _app(monkeypatch, tmp_path, GLUCOTWIN_PUBLIC_IP_RPM=2, GLUCOTWIN_PUBLIC_VISITOR_RPM=100)
    c = _client(app)
    codes = [c.get(f"{API}/health", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]  # untrusted header ignored: one client IP
    app = _app(monkeypatch, tmp_path, GLUCOTWIN_PUBLIC_IP_RPM=2, GLUCOTWIN_PUBLIC_VISITOR_RPM=100,
               GLUCOTWIN_TRUST_PROXY=1)
    c = _client(app)
    codes = [c.get(f"{API}/health", headers={"X-Forwarded-For": f"10.0.0.{i}, 172.16.0.1"}).status_code
             for i in range(3)]
    assert codes == [200, 200, 200]


@pytest.mark.parametrize("public", [False, True])
def test_static_web_app(synthetic_ready, tmp_path, monkeypatch, public):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>GlucoTwin</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside")
    c = _client(_app(monkeypatch, tmp_path, public=public, GLUCOTWIN_WEB_DIST=dist))
    for path in ("/", "/app/review-queue", "/app/sessions/abc"):
        r = c.get(path)
        assert r.status_code == 200 and "<title>GlucoTwin</title>" in r.text and r.headers["cache-control"] == "no-cache"
    r = c.get("/assets/app.js")
    assert r.text == "console.log(1)" and "immutable" in r.headers["cache-control"]
    assert "outside" not in c.get("/../secret.txt").text and "outside" not in c.get("/%2e%2e/secret.txt").text
    r = c.get(f"{API}/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert c.get(f"{API}/health").json()["public_demo"] is public
