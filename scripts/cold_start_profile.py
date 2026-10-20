"""Exploratory cold-start check: does the static profile help population forecasts in a new person's first hours?

NOT pre-specified. Chosen after the frozen experiments showed no reliable benefit from the profile (EHR-like inputs:
age, sex, BMI, HbA1c, fasting glucose and insulin, triglycerides, HDL) on people held out over their whole recordings.
Nothing is fitted and no assessment is re-opened: every number comes from the saved outer-fold predictions of
gt-nested-2026-10-12-v1 (30/60 min) and gt-2h-2026-10-20 (30/60/120 min).

Scope: track multimodal_5min, mode "off" (population model, no personalisation), quality != "insufficient", finite
target and forecast. Each with-profile pipeline is paired with its no-profile twin on the origins both scored, then
split by time since the first reading of the recording (first 6 h, 6-24 h, after 24 h; whole recording for reference).
Per stratum: per-person MAE (people with >= 20 paired origins), macro mean, paired difference (profile minus
no-profile) with a participant-cluster bootstrap 95 % interval (glucotwin.research.metrics.paired_bootstrap, 2000
resamples, seed 20261012 for every comparison) and the number of people better with the profile.

Usage:  uv run python scripts/cold_start_profile.py   (writes reports/cold_start_profile.md only)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from glucotwin.research import metrics as M

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "reports/cold_start_profile.md"
TRACK, MODE = "multimodal_5min", "off"
NBOOT, SEED, MIN_ORIGINS = 2000, 20261012, 20
EXPERIMENTS = [("gt-nested-2026-10-12-v1", (30, 60)), ("gt-2h-2026-10-20", (30, 60, 120))]
PAIRS = [("LightGBM", "lightgbm_l2:dyn-prof-v2", "lightgbm_l2:dyn-v2"),
         ("CatBoost", "catboost:dyn-prof-v2", "catboost:dyn-v2"),
         ("Ridge", "ridge:dyn-prof-v2", "ridge:dyn-v2")]
STRATA = [("First 6 h", 0.0, 360.0), ("6–24 h", 360.0, 1440.0), ("After 24 h", 1440.0, np.inf),
          ("Whole recording", 0.0, np.inf)]
COLS = ["fold", "patient_id", "origin", "elapsed_min", "horizon", "pipeline", "final", "target", "quality"]


def load(exp: str) -> pd.DataFrame:
    path = ROOT / "artifacts/research" / exp / "assessment" / "predictions.parquet"
    pls = [p for _, a, b in PAIRS for p in (a, b)]
    d = pd.read_parquet(path, columns=COLS + ["track", "mode"],
                        filters=[("track", "==", TRACK), ("mode", "==", MODE), ("pipeline", "in", pls)])
    ok = (d["quality"] != "insufficient") & np.isfinite(d["target"]) & np.isfinite(d["final"])
    return d[ok].drop(columns=["track", "mode"])


def compare(d: pd.DataFrame, exp: str, horizons: tuple[int, ...]) -> tuple[list[dict], list[dict]]:
    rows, pairing = [], []
    present = set(d["pipeline"].unique())
    for model, with_p, without_p in PAIRS:
        if with_p not in present or without_p not in present:
            continue
        for h in horizons:
            key = ["patient_id", "origin"]
            a = d[(d["pipeline"] == with_p) & (d["horizon"] == h)]
            b = d[(d["pipeline"] == without_p) & (d["horizon"] == h)]
            m = a.merge(b[key + ["final"]], on=key, suffixes=("_p", "_n"), validate="one_to_one")
            pairing.append({"experiment": exp, "model": model, "horizon": h, "with": len(a), "without": len(b),
                            "paired": len(m)})
            m["err_p"] = np.abs(m["final_p"] - m["target"])
            m["err_n"] = np.abs(m["final_n"] - m["target"])
            for stratum, lo, up in STRATA:
                s = m[(m["elapsed_min"] >= lo) & (m["elapsed_min"] < up)]
                g = s.groupby("patient_id")
                n = g.size()
                keep = n[n >= MIN_ORIGINS].index
                ep, en = g["err_p"].mean().loc[keep], g["err_n"].mean().loc[keep]
                r = M.paired_bootstrap(ep, en, NBOOT, SEED)
                rows.append({"experiment": exp, "model": model, "stratum": stratum, "horizon": h,
                             "people_any": int(n.size), "people": int(keep.size),
                             "origins": int(n.loc[keep].sum()),
                             "elapsed_min_first": float(s["elapsed_min"].min()) if len(s) else None,
                             "mae_without": float(en.mean()) if keep.size else None,
                             "mae_with": float(ep.mean()) if keep.size else None,
                             "diff": r["mean_diff"], "lo": r["ci95"][0], "hi": r["ci95"][1],
                             "better": r["improved"], "worse": r["worsened"]})
    return rows, pairing


def fmt(x: float | None, sign: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x:+.2f}" if sign else f"{x:.2f}"


def ci(r: dict) -> str:
    return f"{fmt(r['diff'], True)} [{fmt(r['lo'], True)}, {fmt(r['hi'], True)}]"


def reading(rows: list[dict]) -> str:
    """One paragraph, driven by the numbers so that a rerun cannot leave stale prose behind."""
    ok = [r for r in rows if r["diff"] is not None]
    idx = {(r["experiment"], r["model"], r["stratum"], r["horizon"]): r for r in ok}
    first = [r for r in ok if r["stratum"] == "First 6 h"]
    trees = [r for r in first if r["model"] != "Ridge"]
    below = [r for r in trees if r["hi"] < 0]
    tree_above = [r for r in trees if r["lo"] > 0]
    ridge = [r for r in first if r["model"] == "Ridge"]
    stratified = [r for r in ok if r["stratum"] != "Whole recording"]
    per_person = {round(r["origins"] / r["people"]) for r in first if r["people"]}
    exps = list(dict.fromkeys(r["experiment"] for r in ok))
    rng = (min(r["diff"] for r in trees), max(r["diff"] for r in trees)) if trees else (None, None)

    if not below:
        out = (f"**No reliable cold-start benefit.** For LightGBM and CatBoost all {len(trees)} first-6-hour differences "
               f"(profile minus no-profile, {fmt(rng[0], True)} to {fmt(rng[1], True)} mg/dL) have a 95 % interval that "
               "includes zero" + (" or lies above it" if tree_above else "") + ".")
    else:
        parts, whole_too = [], []
        for r in below:
            w = idx.get((r["experiment"], r["model"], "Whole recording", r["horizon"]))
            other = [idx[k] for e in exps if e != r["experiment"]
                     and (k := (e, r["model"], "First 6 h", r["horizon"])) in idx]
            txt = f"{r['model']} {r['horizon']} min in `{r['experiment']}`, {ci(r)}, {r['better']}/{r['people']} better"
            extra = ([f"whole recording {ci(w)}"] if w else []) + \
                    [f"same comparison in `{o['experiment']}` {ci(o)}" for o in other]
            parts.append(txt + (f" ({'; '.join(extra)})" if extra else ""))
            if w and w["hi"] < 0:
                whole_too.append((r, w))
        silent = [e for e in exps if not any(r["experiment"] == e for r in below)]
        out = (f"**The profile may help the tree models in the first 6 hours, but this is not a reliable cold-start "
               f"benefit.** {len(below)} of {len(trees)} first-6-hour differences for LightGBM and CatBoost have a 95 % "
               "interval below zero: " + "; ".join(parts) + ".")
        if silent:
            out += (" None comes from " + " or ".join(f"`{e}`" for e in silent) +
                    ", whose sibling fits on the same people show no first-6-hour interval below zero.")
        for r, w in whole_too:
            lgb = idx.get((r["experiment"], "LightGBM", "Whole recording", r["horizon"]))
            notes = (["the frozen reports compared the profile for LightGBM and Ridge only"]
                     if r["model"] == "CatBoost" else [])
            if lgb and r["model"] != "LightGBM" and lgb["mae_without"] < w["mae_without"]:
                notes.append(f"without the profile {r['model']} is weaker than LightGBM at this horizon, MAE "
                             f"{fmt(w['mae_without'])} vs {fmt(lgb['mae_without'])}; with it, {fmt(w['mae_with'])} vs "
                             f"LightGBM's {fmt(lgb['mae_with'])}")
            out += (f" The {r['model']} {r['horizon']}-min benefit holds over the whole recording as well, so it is not "
                    "specific to the first hours" + (f" ({'; '.join(notes)})" if notes else "") + ".")
        rest = [r for r in below if (r, idx.get((r["experiment"], r["model"], "Whole recording", r["horizon"])))
                not in whole_too]
        if rest:
            out += (" For the " + ("other" if whole_too else "") + f" {len(rest)}, the whole recording points the same "
                    "way with an interval that includes zero, so the larger early difference is as consistent with noise "
                    "as with a real early effect.")
    if ridge:
        r_above = [r for r in ridge if r["lo"] > 0]
        out += (f" Ridge with the profile is worse: {len(r_above)} of {len(ridge)} first-6-hour intervals lie above zero "
                f"({fmt(min(r['diff'] for r in ridge), True)} to {fmt(max(r['diff'] for r in ridge), True)} mg/dL), as "
                "over the whole recording.")
    same_ridge = len(exps) == 2 and all(
        abs(r["diff"] - idx[k]["diff"]) < 1e-9 for r in ok if r["model"] == "Ridge" and r["experiment"] == exps[0]
        and (k := (exps[1], "Ridge", r["stratum"], r["horizon"])) in idx)
    out += (" Caveats: 14 people (2–3 per fold), each person's first 6 hours hold only "
            + "/".join(str(n) for n in sorted(per_person)) + " scored origins (one stretch at the start of the "
            f"recording, from 60 minutes of history onward); {len(stratified)} stratified intervals are shown, so a few "
            "excluding zero are expected by chance; the two experiments share people and folds"
            + (" (their Ridge numbers are identical)" if same_ridge else "") + ", so they are not independent "
            "replications. In mode \"off\" the population model never learns the person and its inputs reach back at "
            "most 180 minutes, so the first hours differ from later ones in a shorter glucose history and in what the "
            "person did then, not in what the twin knows about them; personalised modes, where cold start matters most, "
            "are not examined. At most this is a hypothesis for a pre-specified test on new people; nothing here changes "
            "the frozen conclusions or the served model.")
    return out


def render(results: dict[str, list[dict]], pairing: list[dict]) -> str:
    out = ["# Cold start: does the profile help in a new person's first hours?", "",
           "**Exploratory, not pre-specified.** This look was chosen after the frozen experiments showed that the static "
           "profile (EHR-like inputs: age, sex, BMI, HbA1c, fasting glucose and insulin, triglycerides, HDL) gave no "
           "reliable benefit on people held out over their whole recordings, so it is a search for a subgroup where "
           "it might help and must be read as hypothesis-generating. The 14 CGMacros Type 2 people (2–3 per participant "
           "fold, 5 folds) were already inspected in those experiments. Nothing was fitted and no assessment was "
           "re-opened: every number comes from the saved outer-fold predictions of `gt-nested-2026-10-12-v1` (30 and "
           "60 min) and `gt-2h-2026-10-20` (30, 60 and 120 min), track `multimodal_5min`, mode `off` (population "
           "model, no personalisation: the cold-start case), excluding origins with insufficient quality or without a "
           "target. Each pipeline with the profile is paired with its twin without it on the origins both scored. Time "
           "is minutes since the recording's first reading. Per stratum: mean absolute error per person (people with at "
           f"least {MIN_ORIGINS} paired origins in that stratum), then the macro mean; the difference is profile minus "
           "no-profile (negative = profile better) with a participant-cluster bootstrap 95 % interval "
           f"({NBOOT} resamples, seed {SEED}).", ""]
    for exp, rows in results.items():
        out += [f"## `{exp}`", "",
                "| Model | Time since first reading | Horizon | People (≥ 20 origins / any) | Origins | "
                "MAE without → with profile, mg/dL | Difference [95 % CI], mg/dL | Better with profile |",
                "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            label = r["stratum"] if r["stratum"] != "Whole recording" else "*Whole recording (reference)*"
            out.append(f"| {r['model']} | {label} | {r['horizon']} min | {r['people']} / {r['people_any']} | "
                       f"{r['origins']:,} | {fmt(r['mae_without'])} → {fmt(r['mae_with'])} | "
                       f"{fmt(r['diff'], True)} [{fmt(r['lo'], True)}, {fmt(r['hi'], True)}] | "
                       f"{r['better']}/{r['people']} |")
        firsts = [r["elapsed_min_first"] for r in rows if r["stratum"] == "First 6 h" and r["elapsed_min_first"] is not None]
        drop = [p for p in pairing if p["experiment"] == exp and (p["paired"] != p["with"] or p["paired"] != p["without"])]
        out += ["", f"Scored origins in the first 6 h start at {min(firsts):.0f} min (60 minutes of history are "
                "required). " + ("Pairing kept every scored origin." if not drop else
                                 "Pairing dropped origins scored by only one pipeline: " + "; ".join(
                                     f"{p['model']} {p['horizon']} min ({p['with']} with, {p['without']} without, "
                                     f"{p['paired']} paired)" for p in drop) + "."), ""]
    all_rows = [r for rows in results.values() for r in rows]
    out += ["## Reading", "", reading(all_rows), "",
            "Regenerate: `uv run python scripts/cold_start_profile.py`.", ""]
    return "\n".join(out)


def main() -> int:
    results, pairing = {}, []
    for exp, horizons in EXPERIMENTS:
        rows, pr = compare(load(exp), exp, horizons)
        results[exp], pairing = rows, pairing + pr
    md = render(results, pairing)
    OUT_MD.write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
