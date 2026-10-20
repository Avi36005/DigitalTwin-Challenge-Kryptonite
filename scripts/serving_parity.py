"""Online/offline parity of the serving model, saved as a machine-readable artifact.

Replays every participant with final-test forecasts through the ONLINE twin engine exactly as a replay session does
(`Catalog` source timeline, events released by the replay clock, one day per `advance` call, adaptation collecting
from each participant's training end) and compares every final-test forecast with the saved OFFLINE test prediction of
the serving pipeline (`artifacts/experiments/<id>/predictions.parquet`, serving personalisation). The API displays
forecasts rounded to 0.1 mg/dL, so the tolerance is 0.05 mg/dL — the tolerance stated in reports/verification.md.

Writes artifacts/verification/serving_parity_<model>.json (git-ignored; includes per-participant counts) and the
public summary reports/serving_parity.json (aggregate only: no participant IDs or rows).

Usage:  uv run python scripts/serving_parity.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from glucotwin.config import paths
from glucotwin.dataset import load_settings
from glucotwin.serving import load_serving
from glucotwin.twin import TwinEngine
from glucotwin_api.catalog import Catalog

ROOT = Path(__file__).resolve().parents[1]
TOLERANCE = 0.05  # display rounding to 0.1 mg/dL; unchanged from reports/verification.md
DAY = 1440.0


def revision() -> dict[str, object]:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    return {"commit": sha, "dirty": dirty}


def main() -> int:
    t0 = time.perf_counter()
    serving = load_serving("dataset_replay")
    if serving is None:
        sys.exit("No serving model registered for dataset_replay.")
    cfg = json.loads((paths().root / "artifacts/models" / serving.model_version / "serving.json").read_text())
    manifest = json.loads((paths().root / "artifacts/models" / serving.model_version / "manifest.json").read_text())
    exp = cfg["experiment_id"]
    metrics = json.loads((paths().artifacts / "experiments" / exp / "metrics.json").read_text())
    label, pers = metrics["selection"]["selected_label"], metrics["selection"]["serving_personalization"]
    off = pd.read_parquet(paths().artifacts / "experiments" / exp / "predictions.parquet")
    off = off[(off["model"] == label) & (off["personalization"] == pers) & (off["segment"] == "test")
              & np.isfinite(off["predicted"])]
    horizons = sorted(int(h) for h in off["horizon"].unique())

    cat = Catalog()
    event_def = load_settings().event
    per: dict[str, dict] = {}
    diffs: list[np.ndarray] = []
    missing = 0
    for pid, o in off.groupby("patient_id"):
        tl = cat.timeline(pid)
        b = cat.boundaries.get(pid)
        eng = TwinEngine("parity", 1, cat.meta(pid), serving, event_def, b, b.train_end if b is not None else -np.inf)
        online: dict[tuple[float, int], float] = {}
        clock = tl.start
        while clock < tl.end - 1e-6:
            clock = min(clock + DAY, tl.end)
            for f in eng.advance(tl.released(clock), clock):
                for e in f["estimates"]:
                    if e["predicted_mg_dl"] is not None:
                        online[(round(f["_origin"], 6), int(e["horizon_minutes"]))] = float(e["predicted_mg_dl"])
        got = np.array([online.get((round(float(r.origin), 6), int(r.horizon)), np.nan) for r in o.itertuples()])
        d = np.abs(got - o["predicted"].to_numpy(float))
        miss = int(np.isnan(got).sum())
        missing += miss
        diffs.append(d[np.isfinite(d)])
        per[pid] = {"compared": int(np.isfinite(d).sum()), "missing_online": miss,
                    "max_abs_diff": float(np.nanmax(d)) if np.isfinite(d).any() else None}
    alld = np.concatenate(diffs) if diffs else np.array([])
    over = int((alld > TOLERANCE + 1e-9).sum())
    out = {
        "check": "online twin engine replay vs saved offline final-test predictions",
        "model_version": serving.model_version, "experiment_id": exp, "pipeline": label, "personalization": pers,
        "feature_set_id": manifest["feature_set_id"], "transform_fingerprint": manifest["transform_fingerprint"],
        "data_fingerprint": cfg.get("data_fingerprint"), "split_hash": cfg.get("split_hash"),
        "segment": "test", "horizons_minutes": horizons, "participants": len(per),
        "offline_forecasts": int(len(off)), "compared": int(alld.size), "missing_online": missing,
        "tolerance_mg_dl": TOLERANCE, "tolerance_basis": "API displays forecasts rounded to 0.1 mg/dL",
        "max_abs_diff_mg_dl": float(alld.max()) if alld.size else None, "over_tolerance": over,
        "outcome": "pass" if alld.size and over == 0 and missing == 0 else "fail",
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"), "revision": revision(),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    vdir = paths().artifacts / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"serving_parity_{serving.model_version}.json").write_text(json.dumps({**out, "per_participant": per}, indent=1))
    (ROOT / "reports/serving_parity.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if out["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
