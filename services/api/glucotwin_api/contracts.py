"""Export the OpenAPI contract and schema-valid example payloads to packages/contracts.

Examples are produced by the real service running in synthetic mode (no dataset required), then
validated against the Pydantic models. They are fictional and labelled synthetic.
"""

from __future__ import annotations

import json

from glucotwin.config import paths
from glucotwin.schemas import (
    ErrorEnvelope,
    LatestForecast,
    PatientDetail,
    ReplaySession,
    SessionProfile,
)


def export() -> str:
    from fastapi.testclient import TestClient

    from .app import create_app

    out = paths().root / "packages" / "contracts"
    ex_dir = out / "examples"
    ex_dir.mkdir(parents=True, exist_ok=True)
    app = create_app()
    (out / "openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
    c = TestClient(app)
    examples: dict[str, tuple[type, dict]] = {}

    a = c.get("/api/v1/patients/SYN-A").json()
    examples["patient_detail_complete_synthetic.json"] = (PatientDetail, a)
    s = c.post("/api/v1/replay/sessions", json={"patient_id": "SYN-A", "mode": "synthetic_demo"}).json()
    examples["replay_session_synthetic_ready.json"] = (ReplaySession, s)
    prof = c.get(f"/api/v1/replay/sessions/{s['id']}/profile").json()
    examples["session_profile_nullable_field_synthetic.json"] = (SessionProfile, prof)
    c.post(f"/api/v1/replay/sessions/{s['id']}/control", json={"action": "step", "steps": 6})
    f = c.get(f"/api/v1/replay/sessions/{s['id']}/forecast").json()
    examples["forecast_insufficient_history_synthetic.json"] = (LatestForecast, f)
    c.post(f"/api/v1/replay/sessions/{s['id']}/control", json={"action": "step", "steps": 30})
    f = c.get(f"/api/v1/replay/sessions/{s['id']}/forecast").json()
    examples["forecast_ok_synthetic.json"] = (LatestForecast, f)
    # a valid forecast whose interval is unavailable (built from the real payload, interval removed)
    nf = json.loads(json.dumps(f))
    for e in nf["forecast"]["estimates"]:
        e.update({"lower_mg_dl": None, "upper_mg_dl": None, "interval_level": None, "interval_status": "unavailable"})
    examples["forecast_interval_unavailable_synthetic.json"] = (LatestForecast, nf)
    bad = c.post(f"/api/v1/replay/sessions/{s['id']}/control", json={"action": "seek"}).json()
    examples["error_malformed_control_command.json"] = (ErrorEnvelope, bad)

    written = []
    for name, (model, payload) in examples.items():
        model.model_validate(payload)  # fail loudly if an example drifts from the contract
        (ex_dir / name).write_text(json.dumps(payload, indent=2) + "\n")
        written.append(name)
    return f"Wrote {out / 'openapi.json'} and {len(written)} validated examples to {ex_dir}"


if __name__ == "__main__":
    print(export())
