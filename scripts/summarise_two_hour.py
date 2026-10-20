"""Summarise the two-hour research experiment (gt-2h-2026-10-20, decision D-043) from its saved outer-fold assessment.

Every number is computed from artifacts/research/gt-2h-2026-10-20/assessment/ with the nested report's own helpers
(per-participant pooling, paired participant bootstrap, one-to-one warning matching), so it is directly comparable with
gt-nested-2026-10-12-v1. `glucotwin research report` is not used: it writes the v1 report files.

Usage:  uv run python scripts/summarise_two_hour.py   (after `glucotwin research develop` and `assess` for gt-2h-2026-10-20)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from glucotwin.research import metrics as M
from glucotwin.research.protocol import load_frozen, load_protocol, research_dir
from glucotwin.research.report import (
    _agg_events,
    _pipelines,
    _r,
    forecast_row,
    interval_rows,
    per_participant_series,
    pseudo_map,
    resolve,
)

ROOT = Path(__file__).resolve().parents[1]
EXP = "gt-2h-2026-10-20"
TRACK = "multimodal_5min"
OUT_MD = ROOT / "reports/two_hour_benchmark.md"


def build() -> dict:
    proto = load_protocol(EXP)
    root = research_dir(EXP)
    nboot, seed = int(proto["evaluation"]["bootstrap_resamples"]), int(proto["random_seed"])
    horizons = [int(h) for h in proto["horizons_minutes"]]
    preds = pd.read_parquet(root / "assessment" / "predictions.parquet")
    preds = preds[preds["track"] == TRACK]
    ev = json.loads((root / "assessment" / "events.json").read_text())["events"]
    opened = json.loads((root / "assessment" / "opened.json").read_text())
    pls = _pipelines(EXP, TRACK)
    pmap = pseudo_map(pls)

    rows = {}
    for name, mode in [("persistence:-", "off"), ("selected", "off"), ("selected", "final"),
                       ("lightgbm_l2:cgm-only-v1", "off"), ("lightgbm_l2:dyn-v2", "off"),
                       ("lightgbm_l2:dyn-prof-v2", "off"), ("ridge:cgm-only-v1", "off"), ("ridge:dyn-v2", "off"),
                       ("ridge:dyn-prof-v2", "off")]:
        df = resolve(preds, pmap, name, mode)
        if df.empty:
            continue
        rows[f"{name}|{mode}"] = {
            "horizons": {str(h): {k: v for k, v in forecast_row(df, h, 0).items() if k != "per_participant_mae"}
                         for h in horizons},
            "coverage": {str(h): interval_rows(df, h, proto)["global"].get("coverage_pooled") for h in horizons}}

    comps = []
    for title, a, b in [("Selected (personalised) minus persistence", ("selected", "final"), ("persistence:-", "off")),
                        ("Profile (EHR-like) inputs: LightGBM dyn-prof-v2 minus dyn-v2", ("lightgbm_l2:dyn-prof-v2", "off"),
                         ("lightgbm_l2:dyn-v2", "off")),
                        ("Profile (EHR-like) inputs: Ridge dyn-prof-v2 minus dyn-v2", ("ridge:dyn-prof-v2", "off"),
                         ("ridge:dyn-v2", "off")),
                        ("Wearable inputs: LightGBM dyn-v2 minus CGM-only", ("lightgbm_l2:dyn-v2", "off"),
                         ("lightgbm_l2:cgm-only-v1", "off"))]:
        da, db = resolve(preds, pmap, *a), resolve(preds, pmap, *b)
        for h in horizons:
            r = M.paired_bootstrap(per_participant_series(da, h), per_participant_series(db, h), nboot, seed + h)
            comps.append({"comparison": title, "horizon": h, "mean_difference": _r(r["mean_diff"], 2),
                          "ci95": [_r(x, 2) for x in r["ci95"]], "better_for": r["improved"],
                          "participants": r["n_participants"]})

    warn = []
    for name, mode in [("selected", "final"), ("persistence:-", "off")]:
        for H in (60, 120):
            sub = [e for e in ev if e["track"] == TRACK and e["horizon"] == H and e["policy"] == "primary" and e["mode"] == mode
                   and e["pipeline"] == (pmap.get(e["fold"], {}).get(name) if name == "selected" else name)]
            if sub:
                agg = _agg_events(sub, nboot, seed + H)
                warn.append({"pipeline": name, "mode": mode, "horizon": H,
                             **{k: agg.get(k) for k in ("status", "true_onsets", "detected_onsets", "missed_onsets",
                                                         "warning_episodes", "false_alarms", "recall", "precision",
                                                         "false_alarms_per_observed_day", "recall_ci95",
                                                         "false_alarms_per_observed_day_ci95", "qualified_lead_median",
                                                         "qualified_lead_iqr", "episode_start_to_onset_median",
                                                         "thresholds_by_fold", "folds_without_threshold")}})
    doc = load_frozen(EXP)
    return {"experiment_id": EXP, "frozen_at": doc["frozen_at"], "protocol_hash": doc["protocol_hash"],
            "split_hash": doc["split_hash"], "assessment_opened": opened,
            "participants": int(preds["patient_id"].nunique()),
            "selected_by_fold": {f: pl["selection"]["selected"] for f, pl in pls.items()},
            "forecasts": rows, "comparisons": comps, "warnings": warn}


def fmt_ci(c: dict) -> str:
    lo, hi = c["ci95"]
    return f"{c['mean_difference']:+.2f} [{lo:+.2f}, {hi:+.2f}], {c['better_for']}/{c['participants']}"


def render(s: dict) -> str:
    f = s["forecasts"]
    hs = ["30", "60", "120"]
    names = {"persistence:-|off": "Persistence", "selected|off": "Selected pipeline, population only",
             "selected|final": "**Selected pipeline, personalised** (the rule's choice per fold)",
             "lightgbm_l2:cgm-only-v1|off": "LightGBM, CGM only", "lightgbm_l2:dyn-v2|off": "LightGBM, CGM + wearable",
             "lightgbm_l2:dyn-prof-v2|off": "LightGBM, CGM + wearable + profile (EHR-like)",
             "ridge:cgm-only-v1|off": "Ridge, CGM only", "ridge:dyn-v2|off": "Ridge, CGM + wearable",
             "ridge:dyn-prof-v2|off": "Ridge, CGM + wearable + profile (EHR-like)"}
    out = [f"# Two-hour benchmark — `{s['experiment_id']}`",
           "",
           "Research experiment (decision D-043), declared and frozen before any fit on 20 Oct 2026, the submission day. "
           f"Protocol frozen {s['frozen_at']} (hash `{s['protocol_hash'][:12]}`, split `{s['split_hash'][:12]}`); "
           f"outer-fold assessment opened once at {s['assessment_opened'].get('opened_at', '—')}. "
           f"{s['participants']} CGMacros Type 2 people, each held out entirely once (5 participant folds, same folds as "
           "`gt-nested-2026-10-12-v1`). These people were already inspected in earlier experiments, so this is internal "
           "validation, not untouched evidence. Nothing was promoted; the demo model is unchanged.",
           "",
           "Selected per fold: " + ", ".join(f"{k} `{v}`" for k, v in s["selected_by_fold"].items()) + ".",
           "",
           "## Forecast error on people held out (macro MAE, mg/dL)",
           "",
           "| Pipeline | 30 min | 60 min | 120 min | Range coverage at 120 min (target 80 %) |",
           "|---|---|---|---|---|"]
    for k, label in names.items():
        if k in f:
            cov = f[k]["coverage"].get("120")
            out.append(f"| {label} | " + " | ".join(str(f[k]["horizons"][h]["mae"]) for h in hs) +
                       f" | {'—' if cov is None else f'{100 * cov:.1f} %'} |")
    out += ["", "## Paired differences, mg/dL (negative = first pipeline better; 95 % participant bootstrap; people better)", "",
            "| Comparison | 30 min | 60 min | 120 min |", "|---|---|---|---|"]
    for title in dict.fromkeys(c["comparison"] for c in s["comparisons"]):
        cs = {str(c["horizon"]): c for c in s["comparisons"] if c["comparison"] == title}
        out.append(f"| {title} | " + " | ".join(fmt_ci(cs[h]) if h in cs and cs[h]["mean_difference"] is not None else "—"
                                              for h in hs) + " |")
    out += ["", "## New high-glucose onsets (> 180 mg/dL, sustained 15 min): warnings on people held out", "",
            "Threshold per fold chosen on inner folds only: most onsets warned with at most 2 false alarms per observed "
            "forecastable day. Lead = onset minus the earliest firing that forecast it (within the horizon).", "",
            "| Warning | Onsets warned | False alarms per observed day | Precision | Median lead (IQR), min |",
            "|---|---|---|---|---|"]
    for w in s["warnings"]:
        if w.get("status") != "ok":
            out.append(f"| {names.get(w['pipeline'] + '|' + w['mode'], w['pipeline'])}, {w['horizon']} min | no feasible "
                       f"threshold ({w.get('folds_without_threshold')} folds) | — | — | — |")
            continue
        iqr = w["qualified_lead_iqr"]
        out.append(f"| {names.get(w['pipeline'] + '|' + w['mode'], w['pipeline'])}, **{w['horizon']}-min warning** | "
                   f"{w['detected_onsets']} of {w['true_onsets']} ({100 * w['recall']:.1f} %) | "
                   f"{w['false_alarms_per_observed_day']} | {w['precision']} | {w['qualified_lead_median']} "
                   f"({iqr[0]}–{iqr[1]}) |")
    out += ["", "Regenerate: `uv run python scripts/summarise_two_hour.py`. Raw numbers: "
            f"`artifacts/research/{s['experiment_id']}/two_hour_summary.json`.", ""]
    return "\n".join(out)


def main() -> int:
    s = build()
    (research_dir(EXP) / "two_hour_summary.json").write_text(json.dumps(s, indent=1, default=str))
    OUT_MD.write_text(render(s))
    print(render(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
