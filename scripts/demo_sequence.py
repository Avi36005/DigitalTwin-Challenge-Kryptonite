"""Run the demonstration-video replay sequence against the real API and record what the app shows.

The sequence is deterministic (backend-owned clock, saved model artifacts). Every value written to
reports/demo_sequence.md is read from API responses at run time; nothing is typed in or adjusted.
Participants are chosen by display alias because pseudonyms are salted per installation.

Usage:  uv run python scripts/demo_sequence.py          (needs `make synthetic`; recorded scenes need `make data experiment`)
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "reports/demo_sequence.md"
DAY1 = datetime(2000, 1, 3, tzinfo=UTC)  # study day 1 of the synthetic timeline (docs/replay.md)


def label(iso: str | None) -> str:
    if not iso:
        return "—"
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return f"Day {(t - DAY1).days + 1} · {t:%H:%M}"


def at(day: int, hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    return (DAY1 + timedelta(days=day - 1, hours=h, minutes=m)).isoformat()


class Runner:
    def __init__(self, client):
        self.c = client
        self.scenes: list[dict] = []

    def get(self, path: str) -> dict:
        r = self.c.get(f"/api/v1{path}")
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict) -> dict:
        r = self.c.post(f"/api/v1{path}", json=body)
        r.raise_for_status()
        return r.json()

    def patient_by_alias(self, alias: str) -> dict | None:
        items = self.get("/patients?limit=200")["items"]
        return next((p for p in items if p["display_alias"] == alias), None)

    def meals(self, sid: str) -> list[dict]:
        out, cursor = [], None
        while True:
            page = self.get(f"/replay/sessions/{sid}/events?limit=2000" + (f"&cursor={cursor}" if cursor else ""))
            out += [e for e in page["items"] if e["kind"] == "meal"]
            cursor = page["next_cursor"]
            if not page["has_more"]:
                return out

    def snapshot(self, sid: str, action: str, since: str) -> dict:
        s = self.get(f"/replay/sessions/{sid}")
        lf = self.get(f"/replay/sessions/{sid}/forecast")
        alerts = self.get(f"/replay/sessions/{sid}/alerts")
        twin = self.get(f"/replay/sessions/{sid}/twin")
        f = lf.get("forecast") or {}
        est = {e["horizon_minutes"]: e for e in f.get("estimates") or []}
        risk = next((r for r in f.get("event_risk") or [] if r["horizon_minutes"] == 60), None)
        obs = f.get("observed_glucose") or {}
        meals = self.meals(sid)
        return {
            "action": action,
            "clock": label(s["clock_at"]), "clock_at": s["clock_at"], "revision": s["revision"],
            "freshness": s.get("freshness"),
            "forecast_availability": lf.get("availability"), "forecast_age_minutes": lf.get("age_minutes"),
            "forecast_reasons": lf.get("reasons"),
            "latest_glucose": obs.get("value_mg_dl"), "latest_glucose_at": label(obs.get("observed_at")),
            "quality": (f.get("quality") or {}).get("status"), "quality_reasons": (f.get("quality") or {}).get("reasons"),
            "forecast_30": est.get(30), "forecast_60": est.get(60),
            "risk_60": None if risk is None else {k: risk.get(k) for k in ("score", "score_kind", "state", "alert_threshold", "alert_fired")},
            "personalization": (twin.get("personalization") or {}).get("status"),
            "alerts": [{"issued": label(a["issued_at"]), "alert_id": a["alert_id"], "state": a["state"],
                        "outcome": (a.get("outcome") or {}).get("status"),
                        "onset": label((a.get("outcome") or {}).get("onset_at")),
                        "lead_time_minutes": (a.get("outcome") or {}).get("episode_start_to_onset_minutes",
                                                                         (a.get("outcome") or {}).get("lead_time_minutes")),
                        "qualified_lead_minutes": (a.get("outcome") or {}).get("qualified_lead_minutes")}
                       for a in alerts["items"] if a["issued_at"] >= since],
            "meals_visible": len(meals),
            "last_meal": None if not meals else {"eaten": label(meals[-1]["observed_at"]),
                                                 "logged": label(meals[-1]["available_at"])},
        }

    def scene(self, title: str, purpose: str, patient: dict, mode: str, start_at: str | None, steps: list[tuple]) -> None:
        sid = self.post("/replay/sessions", {"patient_id": patient["patient_id"], "mode": mode,
                                              **({"start_at": start_at} if start_at else {})})["id"]
        since = self.get(f"/replay/sessions/{sid}")["clock_at"]
        snaps = [self.snapshot(sid, "start" + (f" at {label(start_at)}" if start_at else ""), since)]
        for kind, arg, note in steps:
            if kind == "step":
                self.post(f"/replay/sessions/{sid}/control", {"action": "step", "steps": arg})
                act = f"step {arg * 5} min" if arg < 12 else f"step {arg * 5 // 60} h" + (f" {arg * 5 % 60} min" if arg * 5 % 60 else "")
            else:
                self.post(f"/replay/sessions/{sid}/control", {"action": "seek", "seek_to": arg})
                act = f"seek to {label(arg)}"
            snaps.append(self.snapshot(sid, act, since) | {"note": note})
        self.scenes.append({"title": title, "purpose": purpose, "patient_alias": patient["display_alias"],
                            "patient_id": patient["patient_id"], "mode": mode, "snapshots": snaps})


def fmt_est(e: dict | None) -> str:
    if not e or e.get("predicted_mg_dl") is None:
        return "not available"
    s = f"{e['predicted_mg_dl']:.0f}"
    if e.get("lower_mg_dl") is not None:
        s += f" [{e['lower_mg_dl']:.0f}–{e['upper_mg_dl']:.0f}]"
    return s


def render(scenes: list[dict], meta: dict) -> str:
    out = [
        "# Demonstration replay sequence (recorded by `scripts/demo_sequence.py`)",
        "",
        "Generated from live API responses on this installation; regenerate with "
        "`uv run python scripts/demo_sequence.py`. Values are what the dashboard shows at each replay time. "
        "Nothing was edited to make the recording look better: false alarms, late warnings and abstentions are kept.",
        "",
        f"* Generated: {meta['generated']} · serving model (recorded data): `{meta['model_dataset']}` · "
        f"synthetic model: `{meta['model_synthetic']}`",
        "* Participant aliases are stable (`Participant NN` follows the dataset's participant order); the `pt-…` "
        "pseudonyms are salted per installation and will differ on another machine.",
        "* Forecast cells show predicted mg/dL with the 80 % interval in brackets when one is issued. "
        "“Risk (60)” is the uncalibrated warning score in mg/dL above 180, not a probability.",
        "",
    ]
    for sc in scenes:
        out += [f"## {sc['title']}", "", sc["purpose"], "",
                f"Participant **{sc['patient_alias']}** (`{sc['patient_id']}`) · mode `{sc['mode']}` · clock range "
                f"{sc['snapshots'][0]['clock']} → {sc['snapshots'][-1]['clock']}", "",
                "| Action | Replay clock | Latest reading | Latest forecast | 30-min | 60-min | Risk (60) | Personalization | Warnings issued in this scene | Meal records visible |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for s in sc["snapshots"]:
            reading = "none" if s["latest_glucose"] is None else f"{s['latest_glucose']:.0f} at {s['latest_glucose_at'].split(' · ')[1]}"
            q = s["forecast_availability"] or "—"
            if q == "stale" and s["forecast_age_minutes"] is not None:
                q += f", {s['forecast_age_minutes']:.0f} min old"
            if s["quality"]:
                q += f"; quality {s['quality']}"
            reasons = s["quality_reasons"] or s["forecast_reasons"]
            if reasons:
                q += " (" + ", ".join(r if isinstance(r, str) else r.get("code", str(r)) for r in reasons) + ")"
            meal = "none" if not s["last_meal"] else f"{s['meals_visible']}; last released: eaten {s['last_meal']['eaten']}, logged {s['last_meal']['logged']}"
            r = s["risk_60"]
            risk = "—" if not r or r["score"] is None else f"{r['score']:+.0f} ({r['state']})"
            al = "; ".join(f"{a['issued']}: {a['outcome'] or a['state']}" + (f", onset {a['onset'].split(' · ')[1]}, forecast lead {a['qualified_lead_minutes']:.0f} min, first warning {a['lead_time_minutes']:.0f} min before"
                                                                         if a["lead_time_minutes"] is not None and a.get("qualified_lead_minutes") is not None else
                                                                         f", onset {a['onset'].split(' · ')[1]}, lead {a['lead_time_minutes']:.0f} min" if a["lead_time_minutes"] is not None else "")
                           for a in s["alerts"]) or "none"
            out.append(f"| {s['action']}{' — ' + s['note'] if s.get('note') else ''} | {s['clock']} | {reading} | {q} | "
                       f"{fmt_est(s['forecast_30'])} | {fmt_est(s['forecast_60'])} | {risk} | {s['personalization'] or '—'} | {al} | {meal} |")
        out.append("")
    if meta["skipped"]:
        out += ["## Skipped scenes", ""] + [f"* {s}" for s in meta["skipped"]] + [""]
    return "\n".join(out)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="glucotwin-demo-")
    os.environ["GLUCOTWIN_VAR_DIR"] = tmp  # isolated sessions; never touches the running app's state
    from fastapi.testclient import TestClient
    from glucotwin_api.app import create_app

    run = Runner(TestClient(create_app()))
    ready = run.get("/health/ready")
    skipped: list[str] = []
    p01, p12 = run.patient_by_alias("Participant 01"), run.patient_by_alias("Participant 12")
    if ready["dataset"]["ready"] and p01 and p12:
        seg = {s["name"]: s for s in run.get(f"/patients/{p01['patient_id']}")["evaluation_segments"]}
        run.scene("Scene A — recorded data: a false alarm, then a true warning",
                  "Held-out test period of the serving model. Shows saved forecasts, a research warning whose outcome "
                  "is unknown until later, a false alarm, a rewind (new revision) and a true warning.",
                  p01, "dataset_replay", seg["test"]["start_at"],
                  [("step", 12, "orientation"), ("step", 2, "warning issued?"), ("step", 24, "outcome now known"),
                   ("seek", at(9, "20:00"), "rewind/seek creates a new revision"), ("step", 7, ""), ("step", 1, ""),
                   ("step", 6, "outcome of the second warning")])
        seg12 = {s["name"]: s for s in run.get(f"/patients/{p12['patient_id']}")["evaluation_segments"]}
        run.scene("Scene B — recorded data: a real 70-minute sensor gap",
                  "A genuine gap in the native Dexcom readings during this participant's held-out test period.",
                  p12, "dataset_replay", seg12["test"]["start_at"],
                  [("seek", at(9, "10:25"), "before the gap"), ("seek", at(9, "10:50"), "21 min without a reading"),
                   ("seek", at(9, "11:30"), "61 min without a reading"), ("seek", at(9, "11:45"), "readings resume")])
    else:
        skipped.append("Recorded-data scenes A and B: CGMacros not imported or Participant 01/12 not found "
                       "(run `make data experiment`).")
    syn = {p["patient_id"]: p for p in run.get("/patients?limit=200")["items"] if p["mode"] == "synthetic_demo"}
    run.scene("Scene C — synthetic: abstention with a short history",
              "Less than an hour of history: the twin abstains instead of guessing.",
              syn["SYN-E"], "synthetic_demo", None, [("step", 1, ""), ("step", 6, ""), ("step", 12, "")])
    run.scene("Scene D — synthetic: a 2.5-hour sensor outage",
              "The chart leaves the gap empty; reading and forecast are marked stale.",
              syn["SYN-D"], "synthetic_demo", None,
              [("seek", at(2, "06:00"), "before the outage"), ("seek", at(2, "09:30"), "inside the outage")])
    run.scene("Scene E — synthetic: a meal logged 90 minutes late",
              "The meal record appears only once it was logged (its available_at), not when it was eaten.",
              syn["SYN-C"], "synthetic_demo", None, [("seek", at(1, "08:30"), "breakfast eaten at about 08:27"),
               ("seek", at(1, "09:30"), "eaten, not yet logged"), ("seek", at(1, "10:00"), "logged at about 09:57")])

    meta = {"generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "model_dataset": ready["model"]["detail"].split("dataset_replay: ")[-1].split(";")[0],
            "model_synthetic": ready["model"]["detail"].split("synthetic_demo: ")[-1], "skipped": skipped}
    OUT_MD.write_text(render(run.scenes, meta) + "\n")
    print(f"wrote {OUT_MD.relative_to(ROOT)} ({len(run.scenes)} scenes; skipped {len(skipped)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
