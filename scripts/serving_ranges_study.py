"""Prediction ranges for the exact serving pipeline (protocol configs/experiments/gt-ranges-2026-10-21.yaml, D-050).

Point forecasts are the saved adaptive predictions of lightgbm:dyn-prof-v2 in gt-primary-2026-10-13-fusion; only the 80 %
range around them is studied. Shapes: G (one split-conformal quantile per horizon) and T (one per past-only slope_15
stratum). Pre-test check: calibrate on validation, score on calibration. Then the chosen shape is calibrated on
validation + calibration and the inspected test segment is read once for reporting.

Usage:  uv run python scripts/serving_ranges_study.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from glucotwin.config import paths
from glucotwin.data.pipeline import dataset_store_dir
from glucotwin.dataset import experiment_dir
from glucotwin.research.calibration import finite_sample_quantile

ROOT = Path(__file__).resolve().parents[1]
PROTO = yaml.safe_load((ROOT / "configs/experiments/gt-ranges-2026-10-21.yaml").read_text())
EXP = "gt-primary-2026-10-13-fusion"
OUT = ROOT / PROTO["artifacts"]["root"]
LEVEL = float(PROTO["level"])
HS = [30, 60]
MIN_STRATUM = 100
STRATA = ("rising", "steady", "falling")


def stratum(slope: np.ndarray) -> np.ndarray:
    return np.select([slope > 1, slope >= -1, slope < -1], ["rising", "steady", "falling"], "none")


def calibrate(d: pd.DataFrame, shape: str) -> dict:
    out = {}
    for h in HS:
        x = d[d["horizon"] == h]
        r = np.abs(x["predicted"] - x["target"]).to_numpy()
        g = finite_sample_quantile(r, LEVEL)[0]
        q = {"global": g}
        if shape == "T":
            for s in STRATA:
                rs = r[(x["stratum"] == s).to_numpy()]
                q[s] = finite_sample_quantile(rs, LEVEL)[0] if len(rs) >= MIN_STRATUM else g
        out[h] = q
    return out


def score(d: pd.DataFrame, q: dict, shape: str) -> dict:
    out = {}
    for h in HS:
        x = d[d["horizon"] == h]
        half = np.full(len(x), q[h]["global"])
        if shape == "T":
            for s in STRATA:
                half = np.where((x["stratum"] == s).to_numpy(), q[h][s], half)
        hit = np.abs(x["predicted"] - x["target"]).to_numpy() <= half
        per = pd.Series(hit).groupby(x["patient_id"].to_numpy()).mean()
        out[str(h)] = {"coverage": float(hit.mean()), "width_mean": float(2 * half.mean()), "n": int(len(x)),
                       "per_person_min": float(per.min()), "per_person_max": float(per.max()),
                       "by_stratum": {s: {"coverage": float(hit[(x["stratum"] == s).to_numpy()].mean()),
                                          "n": int((x["stratum"] == s).sum())}
                                      for s in STRATA if (x["stratum"] == s).any()}}
    return out


def err(sc: dict) -> float:
    return float(np.mean([abs(sc[str(h)]["coverage"] - LEVEL) for h in HS]))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    edir = paths().artifacts / "experiments" / EXP
    m = json.loads((edir / "metrics.json").read_text())
    label, pers = m["selection"]["selected_label"], m["selection"]["serving_personalization"]
    t = pd.read_parquet(experiment_dir(dataset_store_dir(), EXP) / "origins.parquet", columns=["patient_id", "origin", "slope_15"])
    p = pd.read_parquet(edir / "predictions.parquet")
    p = p[(p["model"] == label) & (p["personalization"] == pers)]
    d = p.merge(t, on=["patient_id", "origin"], how="left", validate="many_to_one")
    d = d[np.isfinite(d["predicted"]) & np.isfinite(d["target"])].copy()
    d["stratum"] = stratum(d["slope_15"].to_numpy(float))
    seg = {s: d[d["segment"] == s] for s in ("validation", "calibration", "test")}

    # incumbent reproduced exactly from the serving artifact
    inc = calibrate(seg["calibration"], "G")
    served = m.get("intervals") or {}
    pre = {shape: score(seg["calibration"], calibrate(seg["validation"], shape), shape) for shape in ("G", "T")}
    eG, eT = err(pre["G"]), err(pre["T"])
    wG = np.mean([pre["G"][str(h)]["width_mean"] for h in HS])
    wT = np.mean([pre["T"][str(h)]["width_mean"] for h in HS])
    adopt_T = (eG - eT) >= 0.01 and wT <= 1.15 * wG
    chosen = "T" if adopt_T else "G"
    pooled = pd.concat([seg["validation"], seg["calibration"]])
    final = {"incumbent_G_calibration": (inc, "G"), "G_pooled": (calibrate(pooled, "G"), "G")}
    if chosen == "T":
        final["T_pooled"] = (calibrate(pooled, "T"), "T")
    test = {k: {"quantiles": {str(h): v[0][h] for h in HS}, **score(seg["test"], v[0], v[1])} for k, v in final.items()}
    doc = {"experiment_id": PROTO["experiment_id"], "pipeline": f"{label} ({pers})", "model_version": m["model_version"],
           "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "served_intervals_in_metrics": served,
           "segments": {k: int(len(v)) for k, v in seg.items()},
           "pre_test_check": {"G": pre["G"], "T": pre["T"], "coverage_error": {"G": eG, "T": eT},
                              "width_mean": {"G": wG, "T": wT}, "adopt_T": bool(adopt_T), "chosen": chosen},
           "test_retrospective": test}
    (OUT / "summary.json").write_text(json.dumps(doc, indent=1, default=float))
    (ROOT / PROTO["artifacts"]["report"]).write_text(render(doc))
    print(render(doc))
    return 0


def render(s: dict) -> str:
    pc = s["pre_test_check"]
    pct = lambda x: f"{100 * x:.1f} %"  # noqa: E731
    out = ["# Prediction ranges for the serving pipeline — `gt-ranges-2026-10-21` (D-050)", "",
           f"Pipeline `{s['pipeline']}` of `{s['model_version']}`; point forecasts fixed, only the 80 % range studied. "
           "Protocol committed before any candidate was computed. Origins: "
           + ", ".join(f"{k} {v:,}" for k, v in s["segments"].items()) + " (both horizons).", "",
           "## Pre-test check (calibrate on validation, score on the later calibration segment; no test data)", "",
           "| Shape | 30 min coverage (width) | 60 min coverage (width) | 60 min per-person range | 60 min rising / steady / falling |",
           "|---|---|---|---|---|"]
    for k, name in (("G", "G — one range per horizon"), ("T", "T — range per past-only trend stratum")):
        r = pc[k]
        bs = r["60"]["by_stratum"]
        out.append(f"| {name} | {pct(r['30']['coverage'])} ({r['30']['width_mean']:.0f}) | {pct(r['60']['coverage'])} "
                   f"({r['60']['width_mean']:.0f}) | {pct(r['60']['per_person_min'])}–{pct(r['60']['per_person_max'])} | "
                   + " / ".join(pct(bs[x]["coverage"]) if x in bs else "—" for x in STRATA) + " |")
    out += ["", f"Mean coverage error: G {100 * pc['coverage_error']['G']:.2f} points, T {100 * pc['coverage_error']['T']:.2f} "
            f"points; mean width G {pc['width_mean']['G']:.1f}, T {pc['width_mean']['T']:.1f} mg/dL. Declared rule (T if ≥ 1.0 "
            f"point better and ≤ 15 % wider): **{'T adopted' if pc['adopt_T'] else 'G kept'}**.", "",
            "## Final test segment, read once (retrospective: this segment was inspected on 11–13 Oct)", "",
            "| Ranges | Half-widths 30 / 60 min | 30 min coverage (width) | 60 min coverage (width) | 60 min per-person range | 60 min rising / steady / falling |",
            "|---|---|---|---|---|---|"]
    names = {"incumbent_G_calibration": "Incumbent (served): G on the calibration segment",
             "G_pooled": "G on validation + calibration", "T_pooled": "**T on validation + calibration (chosen)**"}
    for k, r in s["test_retrospective"].items():
        q = r["quantiles"]
        hw = " / ".join(f"{q[h]['global']:.1f}" if "rising" not in q[h] else
                        f"{q[h]['rising']:.0f}·{q[h]['steady']:.0f}·{q[h]['falling']:.0f}" for h in ("30", "60"))
        bs = r["60"]["by_stratum"]
        out.append(f"| {names[k]} | {hw} | {pct(r['30']['coverage'])} ({r['30']['width_mean']:.0f}) | "
                   f"{pct(r['60']['coverage'])} ({r['60']['width_mean']:.0f}) | {pct(r['60']['per_person_min'])}–"
                   f"{pct(r['60']['per_person_max'])} | " + " / ".join(pct(bs[x]["coverage"]) if x in bs else "—" for x in STRATA) + " |")
    out += ["", "Widths in mg/dL (full range, upper minus lower). Trend strata use `slope_15` at the origin (past readings only). "
            "Test origins are later recordings of the same 14 people, so there is no first-day stratum. Coverage is "
            "pooled over origins; a range is a statement about many forecasts, not a guarantee for one.", "",
            "Regenerate: `uv run python scripts/serving_ranges_study.py`. Raw numbers: "
            "`artifacts/research/gt-ranges-2026-10-21/summary.json`.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
