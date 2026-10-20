"""How much of the time the real warnings fire: a post-hoc check against an always-on alarm, from saved predictions only.

The direct two-hour classifier (gt-2h-clf-2026-10-20, D-044) fired at 97-99 % of eligible moments, which made its episode
counts look perfect (reports/two_hour_classifier.md). This script measures the same quantity for the warnings we do report:

* the demo model's 60-minute warning (gt-primary-2026-10-13-fusion, serving pipeline with adaptation, margin -10 mg/dL)
  and persistence's 60-minute warning, on the final test segment;
* the research regression warnings of gt-2h-2026-10-20 at 60 and 120 minutes (per-fold selected pipeline, personalised,
  per-fold primary threshold) on the outer-fold people held out.

Nothing is fitted and no assessment is re-opened. Scores are rebuilt from the saved forecasts with
``glucotwin.research.warnings.scores`` (max of forecasts for horizons <= H, minus 180 mg/dL), firing and episodes with
``glucotwin.evaluation.alerts.evaluate_patient`` (the code the evaluation and the online twin use). As a guard, the
episode, warned-onset and false-alarm counts are checked against the saved metrics before anything is reported.

Usage:  uv run python scripts/warning_time_share.py   (writes reports/warning_time_share.md only)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from glucotwin.config import load_experiment_config
from glucotwin.data.pipeline import dataset_store_dir
from glucotwin.dataset import experiment_dir
from glucotwin.evaluation import alerts as A
from glucotwin.research import warnings as W
from glucotwin.research.protocol import FINAL, load_frozen, load_protocol, plans_of, research_dir

ROOT = Path(__file__).resolve().parents[1]
DEMO = "gt-primary-2026-10-13-fusion"
RES = "gt-2h-2026-10-20"
CLF = "gt-2h-clf-2026-10-20"
TRACK = "multimodal_5min"
DEMO_CADENCE = 5.0  # native Dexcom G6 cadence; evaluation/run.py event_eval uses the same 5-minute step
OUT_MD = ROOT / "reports/warning_time_share.md"


def measure(t: pd.DataFrame, rows: np.ndarray, issued: np.ndarray, score: np.ndarray, H: int, thr: float, merge: float,
            cadence: float) -> dict:
    """Firing share and episodes of one warning on ``rows`` of origin table ``t`` (score aligned to ``t``)."""
    pids, o = t["patient_id"].to_numpy(), t["origin"].to_numpy(float)
    elig = t["ew_eligible"].to_numpy(bool)
    lab, onset = t[f"label_{H}"].to_numpy(float), t[f"onset_{H}"].to_numpy(float)
    # identical to the firing mask inside alerts.evaluate_patient
    fire = rows & elig & issued & np.isfinite(score) & (score >= thr)
    resolved = rows & issued & elig & np.isfinite(lab)
    out = {"firing": int(fire.sum()), "eligible": int((rows & issued & elig).sum()), "issued": int((rows & issued).sum()),
           "resolved": int(resolved.sum()), "positive": int((resolved & (lab == 1)).sum()),
           "episodes": 0, "detected": 0, "onsets": 0, "false_alarms": 0, "lengths": [], "leads": [],
           "people": set(pids[rows])}
    for pid in pd.unique(pids[rows]):
        r = pids == pid
        res = A.evaluate_patient(o[r], rows[r], elig[r], issued[r], score[r], lab[r], onset[r], thr, float(H), merge)
        out["episodes"] += len(res.episodes)
        out["detected"] += res.matched_onsets
        out["onsets"] += len(res.detectable_onsets)
        out["false_alarms"] += res.false_alarms
        out["leads"] += res.qualified_leads
        # episode length: first to last firing, plus the one native step the last firing stands for
        out["lengths"] += [ep["last"] - ep["start"] + cadence for ep in res.episodes]
    return out


def pool(parts: list[dict]) -> dict:
    out = {k: sum(p[k] for p in parts) for k in ("firing", "eligible", "issued", "resolved", "positive", "episodes",
                                                 "detected", "onsets", "false_alarms")}
    out["lengths"] = [x for p in parts for x in p["lengths"]]
    out["leads"] = [x for p in parts for x in p["leads"]]
    out["people"] = set().union(*(p["people"] for p in parts))
    return out


def finish(m: dict) -> dict:
    L = m.pop("lengths")
    m["people"] = len(m["people"])
    leads = m.pop("leads")
    m["lead_median"] = float(np.median(leads)) if leads else None
    m["base_rate"] = m["positive"] / m["resolved"] if m["resolved"] else None
    m["share_eligible"] = m["firing"] / m["eligible"] if m["eligible"] else None
    m["share_issued"] = m["firing"] / m["issued"] if m["issued"] else None
    m["episode_min_median"] = float(np.median(L)) if L else None
    m["episode_min_iqr"] = [float(np.percentile(L, 25)), float(np.percentile(L, 75))] if L else [None, None]
    return m


def check(what: str, got: dict, saved: dict) -> None:
    pairs = [("episodes", "warning_episodes"), ("detected", "detected_onsets"), ("onsets", "true_onsets"),
             ("false_alarms", "false_alarm_episodes")]
    bad = [(a, got[a], saved[b]) for a, b in pairs if got[a] != saved[b]]
    if bad:
        sys.exit(f"{what}: rebuilt warning does not reproduce the saved metrics {bad}; refusing to report.")


def demo() -> list[dict]:
    exp = load_experiment_config(DEMO)
    H = int(exp["alerts"]["serving_horizon_minutes"])
    merge = float(exp["alerts"]["episode_merge_minutes"])
    event_thr = float(exp["event"]["threshold_mg_dl"])
    edir = ROOT / "artifacts/experiments" / DEMO
    metrics = json.loads((edir / "metrics.json").read_text())
    sel = metrics["selection"]
    serving_name = f"{sel['selected_label']} ({'adaptive' if sel['serving_personalization'] == 'adaptive' else 'population'})"
    t = pd.read_parquet(experiment_dir(dataset_store_dir(), DEMO) / "origins.parquet")
    t = t.sort_values(["patient_id", "origin"], kind="mergesort").reset_index(drop=True)
    rows = (t["segment"] == "test").to_numpy()
    issued = (t["quality"] != "insufficient").to_numpy()
    preds = pd.read_parquet(edir / "predictions.parquet")
    hs = [int(h) for h in exp["horizons_minutes"] if int(h) <= H]
    out = []
    for key, label, model, mode, event_name in [
            ("demo", "Demo model (fusion LightGBM, personalised)", sel["selected_label"], sel["serving_personalization"],
             serving_name),
            ("persistence", "Persistence", "persistence:cgm-only-v1", "off", "persistence")]:
        saved = next(e for e in metrics["events"] if e["model"] == event_name and e["split"] == "test" and e["horizon"] == H)
        thr = float(saved["threshold"])
        final = {}
        for h in hs:
            p = preds[(preds["model"] == model) & (preds["personalization"] == mode) & (preds["horizon"] == h)]
            final[h] = t[["patient_id", "origin"]].merge(p[["patient_id", "origin", "predicted"]], how="left",
                                                         on=["patient_id", "origin"], validate="one_to_one")["predicted"].to_numpy(float)
        score = W.scores(final, H, event_thr)
        m = measure(t, rows, issued, score, H, thr, merge, DEMO_CADENCE)
        check(f"{DEMO} {event_name}", m, saved)
        out.append({"key": key, "warning": f"{label}, {H} min", "where": "final test segment", "horizon": H,
                    "threshold": f"{thr:g}", **finish(m)})
    return out


def research() -> list[dict]:
    proto = load_protocol(RES)
    w = proto["warnings"]
    merge, event_thr = float(w["episode_merge_minutes"]), float(w["event"]["threshold_mg_dl"])
    cadence = float(proto["tracks"][TRACK]["cadence_minutes"])
    horizons = [int(h) for h in proto["horizons_minutes"]]
    root = research_dir(RES)
    tpath = root / "tables" / f"{TRACK}__cgmacros.parquet"
    t = pd.read_parquet(tpath).sort_values(["patient_id", "origin"], kind="mergesort").reset_index(drop=True)
    key = json.loads(tpath.with_suffix(".json").read_text())["cache_key"]
    issued = (t["quality"] != "insufficient").to_numpy()
    pids = t["patient_id"].to_numpy()
    preds = pd.read_parquet(root / "assessment" / "predictions.parquet")
    preds = preds[preds["track"] == TRACK]
    events = json.loads((root / "assessment" / "events.json").read_text())["events"]
    plans = [p for p in plans_of(load_frozen(RES)) if p.fold != FINAL]
    out = []
    for H in (120, 60):
        parts, thrs = [], {}
        for p in plans:
            pl = json.loads((root / "development" / p.fold / TRACK / "pipeline.json").read_text())
            if pl["table_cache_key"] != key:
                sys.exit(f"{p.fold}: cached table differs from the one frozen with the pipeline; refusing to report.")
            lab = pl["selection"]["selected"]
            thr = pl["warnings"][f"{lab}|final|{H}"]["primary"]["threshold"]
            if thr is None:
                sys.exit(f"{p.fold}: no primary threshold at {H} min")
            thrs[p.fold] = float(thr)
            rows = np.isin(pids, list(p.assessment))
            d = preds[(preds["fold"] == p.fold) & (preds["pipeline"] == lab) & (preds["mode"] == "final")]
            final = {}
            for h in horizons:
                merged = t[["patient_id", "origin"]].merge(d.loc[d["horizon"] == h, ["patient_id", "origin", "final"]],
                                                           how="left", on=["patient_id", "origin"], validate="one_to_one")
                final[h] = np.where(rows, merged["final"].to_numpy(float), np.nan)
            score = W.scores(final, H, event_thr)
            m = measure(t, rows, issued, score, H, float(thr), merge, cadence)
            saved = next(e for e in events if e["track"] == TRACK and e["fold"] == p.fold and e["pipeline"] == lab
                         and e["mode"] == "final" and e["horizon"] == H and e["policy"] == "primary")
            check(f"{RES} {p.fold} {lab} {H} min", m, saved)
            parts.append(m)
        out.append({"key": f"research{H}", "warning": f"Research regression warning ({RES}), {H} min, selected per "
                    "fold, personalised", "where": "outer-fold people held out", "horizon": H,
                    "threshold": ", ".join(f"{f} {v:g}" for f, v in thrs.items()), **finish(pool(parts))})
    return out


def classifier_shares() -> dict | None:
    p = ROOT / "artifacts/research" / CLF / "summary.json"
    if not p.exists():
        return None
    r = json.loads(p.read_text())["results"]
    return {k: v.get("share_of_eligible_time_warning") for k, v in r.items()}


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def render(rows: list[dict], clf: dict | None) -> str:
    out = ["# How much of the time the warnings fire",
           "",
           "Post-hoc diagnostic, computed from saved forecasts only (no model fitted, no assessment re-opened). The direct "
           "two-hour classifier fired at almost every eligible moment, so its episode counts looked perfect "
           "([two-hour classifier](two_hour_classifier.md)). This checks the warnings we report for the same failure.",
           "",
           "- **Fires at eligible origins**: share of forecast-issued, early-warning-eligible origins (glucose not already "
           "in a high episode) at which the warning fires; the same quantity as the classifier's \"share of eligible time "
           "warning\".",
           "- **Fires at all issued origins**: the same firings over every forecast-issued origin (origins already in a "
           "high episode can never fire).",
           "- **Onset ahead**: share of eligible origins with a resolved label at which a new high onset (> 180 mg/dL, "
           "sustained 15 min) really follows within the horizon, for reference.",
           "- **Episode length**: first to last firing of a warning episode (firings within 30 min merge) plus one 5-minute "
           "step, so a single firing counts as 5 min.",
           "",
           "| Warning | Where (people) | Threshold, mg/dL margin | Fires at eligible origins | Fires at all issued origins "
           "| Onset ahead | Episodes | Episode length, median (IQR), min | Onsets warned |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lo, hi = r["episode_min_iqr"]
        out.append(f"| {r['warning']} | {r['where']} ({r['people']}) | {r['threshold']} | {pct(r['share_eligible'])} "
                   f"({r['firing']:,} of {r['eligible']:,}) | {pct(r['share_issued'])} ({r['firing']:,} of "
                   f"{r['issued']:,}) | {pct(r['base_rate'])} | {r['episodes']} | {r['episode_min_median']:g} "
                   f"({lo:g}–{hi:g}) | {r['detected']} of {r['onsets']} |")
    by = {r["key"]: r for r in rows}
    d, pe, r120, r60 = by["demo"], by["persistence"], by["research120"], by["research60"]

    def vs(r: dict) -> str:
        return "below" if r["share_eligible"] < r["base_rate"] else "above"

    out += ["",
            f"- **Demo 60-minute warning:** it fires at {pct(d['share_eligible'])} of eligible moments on the test segment, "
            f"{vs(d)} the {pct(d['base_rate'])} at which an onset really follows, in episodes of median "
            f"{d['episode_min_median']:g} min, so it is an intermittent warning, not an always-on alarm (retrospective: "
            "this test segment was inspected in earlier experiments).",
            f"- **Persistence 60-minute warning:** it fires at {pct(pe['share_eligible'])} of eligible moments, "
            f"{pe['share_eligible'] / d['share_eligible']:.1f} times as often as the demo warning, to warn "
            f"{pe['detected']} rather than {d['detected']} of {d['onsets']} onsets with {pe['false_alarms']} rather than "
            f"{d['false_alarms']} false alarms.",
            f"- **Research 120-minute warning:** it fires at {pct(r120['share_eligible'])} of eligible moments for people "
            f"held out ({vs(r120)} the {pct(r120['base_rate'])} onset rate), so its {r120['detected']} of "
            f"{r120['onsets']} onsets warned are not bought with an always-on alarm, but most of them are caught late "
            f"(median forecast lead {r120['lead_median']:g} min of the 120 available).",
            f"- **Research 60-minute warning:** it fires at {pct(r60['share_eligible'])} of eligible moments for people "
            f"held out ({vs(r60)} the {pct(r60['base_rate'])} onset rate), median forecast lead "
            f"{r60['lead_median']:g} min; like the 120-minute row this is research on internally re-used people, not "
            "the demo model."]
    if clf:
        vals = [v for v in clf.values() if v is not None]
        out += [f"- **For contrast**, the degenerate two-hour classifier fired at {pct(clf.get('selected'))} of eligible "
                f"moments ({pct(min(vals))}–{pct(max(vals))} across feature sets; read from "
                f"`artifacts/research/{CLF}/summary.json`)."]
    out += ["",
            "Each warning was rebuilt from the saved forecasts and had to reproduce the saved episode, onset and "
            "false-alarm counts before anything was reported. Sources: `artifacts/experiments/gt-primary-2026-10-13-fusion/` "
            "(predictions.parquet, metrics.json) with that experiment's origin table (eligibility, labels, forecast "
            "quality); `artifacts/research/gt-2h-2026-10-20/` (assessment/predictions.parquet, per-fold `pipeline.json`, "
            "cached table).",
            "",
            "Regenerate: `uv run python scripts/warning_time_share.py`.",
            ""]
    return "\n".join(out)


def main() -> int:
    rows = demo() + research()
    md = render(rows, classifier_shares())
    OUT_MD.write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
