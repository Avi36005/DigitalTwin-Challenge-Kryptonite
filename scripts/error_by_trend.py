"""Forecast error of the serving model by glucose trend, from its saved validation-segment predictions only.

The development error analysis of D-048 found errors largest while glucose rises fast and peaks under-forecast. This
script measures the same strata for the exact serving pipeline (selected model, serving personalisation) on the
validation segment of its own experiment — data used for selection, before the test segment — so the workspace can
say when a forecast tends to be less accurate. Nothing is fitted and the test segment is not read.

Trend = the ``slope_15`` feature at the origin (least-squares slope of native readings over the last 15 min,
mg/dL per minute). Errors are macro per-participant MAE (every participant weighted equally).

Usage:  uv run python scripts/error_by_trend.py [--experiment gt-primary-2026-10-13-fusion]
Writes  artifacts/experiments/<id>/error_by_trend.json (read by the evaluation report) and reports/error_by_trend.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from glucotwin.config import paths
from glucotwin.data.pipeline import dataset_store_dir
from glucotwin.dataset import experiment_dir

ROOT = Path(__file__).resolve().parents[1]
SEGMENT = "validation"
# (key, label, lower bound exclusive, upper bound inclusive) in mg/dL per minute
STRATA = [("falling_fast", "Falling > 2 mg/dL/min", -np.inf, -2.0), ("falling", "Falling 1–2 mg/dL/min", -2.0, -1.0),
          ("steady", "Steady (within ±1 mg/dL/min)", -1.0, 1.0), ("rising", "Rising 1–2 mg/dL/min", 1.0, 2.0),
          ("rising_fast", "Rising > 2 mg/dL/min", 2.0, np.inf)]
MIN_PEOPLE = 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", default="gt-primary-2026-10-13-fusion")
    a = ap.parse_args()
    edir = paths().artifacts / "experiments" / a.experiment
    m = json.loads((edir / "metrics.json").read_text())
    label, pers = m["selection"]["selected_label"], m["selection"]["serving_personalization"]
    t = pd.read_parquet(experiment_dir(dataset_store_dir(), a.experiment) / "origins.parquet",
                        columns=["patient_id", "origin", "slope_15"])
    p = pd.read_parquet(edir / "predictions.parquet")
    p = p[(p["model"] == label) & (p["personalization"] == pers) & (p["segment"] == SEGMENT)]
    d = p.merge(t, on=["patient_id", "origin"], how="left", validate="many_to_one")
    d = d[np.isfinite(d["predicted"]) & np.isfinite(d["target"]) & np.isfinite(d["slope_15"])]
    d["err"] = (d["predicted"] - d["target"]).abs()
    rows = []
    for h in sorted(d["horizon"].unique()):
        x = d[d["horizon"] == h]
        for key, lab, lo, hi in [("all", "All origins", -np.inf, np.inf), *STRATA]:
            y = x[(x["slope_15"] > lo) & (x["slope_15"] <= hi)]
            people = int(y["patient_id"].nunique())
            mae = float(y.groupby("patient_id")["err"].mean().mean()) if people >= MIN_PEOPLE else None
            hi_t = y[y["target"] > 180]
            rows.append({"horizon": int(h), "trend": key, "label": lab,
                         "slope_min": None if not np.isfinite(lo) else lo, "slope_max": None if not np.isfinite(hi) else hi,
                         "mae_macro": mae, "origins": int(len(y)), "participants": people,
                         "mean_signed_error_target_above_180": float((hi_t["predicted"] - hi_t["target"]).mean())
                         if len(hi_t) else None})
    out = {"experiment_id": a.experiment, "model_version": m["model_version"], "pipeline": label,
           "personalization": pers, "segment": SEGMENT, "trend_feature": "slope_15 (mg/dL per minute)",
           "weighting": "macro per participant", "min_participants": MIN_PEOPLE,
           "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "rows": rows}
    (edir / "error_by_trend.json").write_text(json.dumps(out, indent=1))
    md = [f"# Forecast error by glucose trend — serving model `{m['model_version']}`", "",
          f"Validation segment of `{a.experiment}` (used for model selection, before the final test segment; the test "
          "segment is not read here). Pipeline "
          f"`{label}` with {pers} personalisation. Trend = `slope_15`, the least-squares slope of native readings over the "
          "last 15 minutes. Macro per-participant MAE in mg/dL; a stratum with fewer than "
          f"{MIN_PEOPLE} participants is not summarised. Descriptive only: it says when forecasts tend to be less "
          "accurate, not why.", "",
          "| Trend | " + " | ".join(f"{h}-min MAE (origins)" for h in sorted(d["horizon"].unique())) + " |",
          "|---|" + "---|" * d["horizon"].nunique()]
    for key, lab, *_ in [("all", "All origins"), *STRATA]:
        cells = []
        for h in sorted(d["horizon"].unique()):
            r = next(r for r in rows if r["horizon"] == h and r["trend"] == key)
            cells.append("—" if r["mae_macro"] is None else f"{r['mae_macro']:.1f} ({r['origins']:,})")
        md.append(f"| {lab} | " + " | ".join(cells) + " |")
    pk = {r["horizon"]: r["mean_signed_error_target_above_180"] for r in rows if r["trend"] == "all"}
    md += ["", "Mean signed error (forecast − actual) when the actual value was above 180 mg/dL: "
           + "; ".join(f"{h} min {v:+.1f} mg/dL" for h, v in pk.items() if v is not None)
           + " — peaks tend to be under-forecast.", "",
           f"Regenerate: `uv run python scripts/error_by_trend.py`. Raw numbers: "
           f"`artifacts/experiments/{a.experiment}/error_by_trend.json`.", ""]
    (ROOT / "reports/error_by_trend.md").write_text("\n".join(md))
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
