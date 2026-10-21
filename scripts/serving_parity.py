"""Online/offline parity of the serving model (or an explicit candidate), saved as a machine-readable artifact.

Replays every participant with final-test forecasts through the ONLINE twin engine exactly as a replay session does
(`Catalog` source timeline, events released by the replay clock, one day per `advance` call, adaptation collecting
from each participant's training end) and compares every final-test forecast with the saved OFFLINE test prediction of
the pipeline (`artifacts/experiments/<id>/predictions.parquet`, serving personalisation). The API displays forecasts
rounded to 0.1 mg/dL, so the tolerance is 0.05 mg/dL — the tolerance stated in reports/verification.md. The outcome is
gated on that display tolerance only. The unrounded online value (population + patient correction, float64, captured
before display rounding) is also compared with the saved float64 offline prediction and reported as the raw maximum
difference; it is informational and never relaxes or replaces the display tolerance.

Default (no options): loads the registered serving model from artifacts/registry.json and writes
artifacts/verification/serving_parity_<model>.json (git-ignored; per-participant counts) and the public summary
reports/serving_parity.json (aggregate only: no participant IDs or rows). This is the incumbent's evidence.

Candidate-scoped check (never switches artifacts/registry.json, never overwrites the incumbent's evidence):
  --model-dir DIR        load this model directory (manifest.json + serving.json, checksums verified) directly
  --registry FILE        or: resolve the serving model from this registry file instead of artifacts/registry.json
  --model-version V      with --registry: check this registered version instead of the registry's serving entry
  --experiment-dir DIR   saved offline metrics.json + predictions.parquet (default artifacts/experiments/<experiment_id>)
  --pipeline LABEL / --personalization NAME   override the selected label / serving personalisation
  --output FILE          aggregate summary (required with any candidate option; may not be the incumbent's files)
  --detail-output FILE   per-participant detail (default: git-ignored
                         artifacts/verification/candidate_parity/<output stem>.per_participant.json)
--output alone (no candidate option) checks the registered serving model but writes only to the given paths.

Usage:  uv run python scripts/serving_parity.py
        uv run python scripts/serving_parity.py --model-dir artifacts/models/<candidate> \
            --experiment-dir artifacts/research/<id>/<run> --output reports/verification/overnight/parity_<candidate>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from glucotwin.config import paths
from glucotwin.dataset import load_settings
from glucotwin.models.population import ArtifactError, PopulationBundle
from glucotwin.serving import ServingModel, load_serving
from glucotwin.twin import TwinEngine
from glucotwin_api.catalog import Catalog

ROOT = Path(__file__).resolve().parents[1]
TOLERANCE = 0.05  # display rounding to 0.1 mg/dL; unchanged from reports/verification.md
DAY = 1440.0
PUBLIC_SUMMARY = ROOT / "reports/serving_parity.json"
PUBLIC_REPORT = ROOT / "reports/serving_parity.md"
CANDIDATE_OPTIONS = ("model_dir", "registry", "model_version", "experiment_dir", "pipeline", "personalization")


def revision() -> dict[str, object]:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    return {"commit": sha, "dirty": dirty}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(directory: Path) -> str:
    """One digest over the sorted ``relative path, file sha256`` lines of a directory (stable across copies)."""
    lines = [f"{p.relative_to(directory).as_posix()}\0{sha256_file(p)}\n"
             for p in sorted(directory.rglob("*")) if p.is_file() and p.name != ".DS_Store"]
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def shown(p: Path) -> str:
    """Repository-relative path when inside the checkout, so saved evidence carries no local home directory."""
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(p.resolve()).replace(str(Path.home()), "~", 1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, help="candidate model directory (manifest.json + serving.json)")
    ap.add_argument("--registry", type=Path, help="registry file to resolve the model from (instead of artifacts/)")
    ap.add_argument("--model-version", help="with --registry: version to check instead of its dataset_replay entry")
    ap.add_argument("--experiment-dir", type=Path, help="directory with the saved metrics.json + predictions.parquet")
    ap.add_argument("--pipeline", help="offline 'model' label to compare (default: metrics selection)")
    ap.add_argument("--personalization", help="offline personalisation to compare (default: metrics selection)")
    ap.add_argument("--output", type=Path, help="aggregate summary JSON (default: reports/serving_parity.json)")
    ap.add_argument("--detail-output", type=Path, help="per-participant detail JSON")
    a = ap.parse_args(argv)
    a.candidate = any(getattr(a, k) is not None for k in CANDIDATE_OPTIONS)
    if a.model_dir is not None and a.registry is not None:
        ap.error("--model-dir and --registry are alternatives; give one")
    if a.model_version is not None and a.registry is None:
        ap.error("--model-version needs --registry")
    if a.candidate and a.output is None:
        ap.error("a candidate-scoped check needs --output (the incumbent's reports/serving_parity.json is never "
                 "overwritten by a candidate)")
    return a


def resolve_outputs(a: argparse.Namespace, model_version: str) -> tuple[Path, Path]:
    """(summary, detail) paths. Refuses to let a candidate-scoped run overwrite the incumbent's evidence files."""
    incumbent_detail = paths().artifacts / "verification" / f"serving_parity_{model_version}.json"
    if a.output is None:
        return PUBLIC_SUMMARY, incumbent_detail
    summary = a.output.resolve()
    # per-participant detail carries participant IDs: by default it goes to the git-ignored artifacts/ tree
    default_detail = paths().artifacts / "verification" / "candidate_parity" / f"{summary.stem}.per_participant.json"
    detail = (a.detail_output or default_detail).resolve()
    protected = {PUBLIC_REPORT.resolve(), incumbent_detail.resolve()}
    if a.candidate:
        protected |= {PUBLIC_SUMMARY.resolve()}
        # any existing per-participant evidence file of a registered model is the incumbent's, never a candidate's
        protected |= {p.resolve() for p in (paths().artifacts / "verification").glob("serving_parity_*.json")}
    for p in (summary, detail):
        if p in protected:
            sys.exit(f"Refusing to write {p}: it holds the incumbent's parity evidence. Choose another --output.")
    if summary == detail:
        sys.exit("--output and --detail-output must differ")
    return summary, detail


def load_model(a: argparse.Namespace) -> tuple[ServingModel, dict[str, Any]]:
    """The model to check and where it came from. Same checksum/feature verification as the serving loader."""
    if a.model_dir is None and a.registry is None:
        serving = load_serving("dataset_replay")
        if serving is None:
            sys.exit("No serving model registered for dataset_replay.")
        reg = paths().artifacts / "registry.json"
        return serving, {"source": "registry", "registry": shown(reg), "registry_sha256": sha256_file(reg)}
    if a.registry is not None:
        reg = json.loads(a.registry.read_text())
        version = a.model_version or reg.get("serving", {}).get("dataset_replay")
        entry = next((m for m in reg.get("models", []) if m.get("model_version") == version), None)
        if entry is None:
            sys.exit(f"Model {version!r} is not in {a.registry}")
        directory = paths().root / entry["artifact_dir"]  # absolute artifact_dir values stay absolute
        source = {"source": "registry", "registry": shown(a.registry), "registry_sha256": sha256_file(a.registry)}
    else:
        directory, version = a.model_dir, None
        source = {"source": "model_dir"}
    directory = directory.resolve()
    try:
        bundle = PopulationBundle.load(directory)
        cfg = json.loads((directory / "serving.json").read_text())
    except (ArtifactError, FileNotFoundError, json.JSONDecodeError) as e:
        sys.exit(f"Cannot load model from {directory}: {e}")
    if version is not None and cfg.get("model_version") != version:
        sys.exit(f"serving.json in {directory} names {cfg.get('model_version')!r}, not {version!r}")
    if cfg.get("feature_set_id") not in (None, bundle.feature_set_id):
        sys.exit(f"serving.json feature set {cfg.get('feature_set_id')!r} differs from the manifest's "
                 f"{bundle.feature_set_id!r}")
    return ServingModel(cfg["model_version"], bundle, cfg, directory), source


def capture_raw(eng: TwinEngine, raw: dict[tuple[float, int], float]) -> bool:
    """Record the unrounded final value (population + correction) of every forecast the engine assembles."""
    build = getattr(eng, "_build_forecast", None)
    if build is None:
        return False

    def wrapped(t, fid, row, quality, reasons, latest_idx, support_ids, pop_t, corr, *rest):
        for h, p in pop_t.items():
            if p is not None:
                raw[(round(float(t), 6), int(h))] = float(p) + float(corr.get(h) or 0.0)
        return build(t, fid, row, quality, reasons, latest_idx, support_ids, pop_t, corr, *rest)

    eng._build_forecast = wrapped
    return True


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    t0 = time.perf_counter()
    serving, source = load_model(a)
    summary_path, detail_path = resolve_outputs(a, serving.model_version)
    mdir = serving.artifact_dir
    cfg = json.loads((mdir / "serving.json").read_text())
    manifest = json.loads((mdir / "manifest.json").read_text())
    exp = cfg["experiment_id"]
    edir = (a.experiment_dir or paths().artifacts / "experiments" / exp).resolve()
    metrics = json.loads((edir / "metrics.json").read_text())
    label = a.pipeline or metrics["selection"]["selected_label"]
    pers = a.personalization or metrics["selection"]["serving_personalization"]
    off = pd.read_parquet(edir / "predictions.parquet")
    off = off[(off["model"] == label) & (off["personalization"] == pers) & (off["segment"] == "test")
              & np.isfinite(off["predicted"])]
    horizons = sorted(int(h) for h in off["horizon"].unique())

    cat = Catalog()
    event_def = load_settings().event
    per: dict[str, dict] = {}
    rows: list[pd.DataFrame] = []
    raw_captured = True
    for pid, o in off.groupby("patient_id"):
        tl = cat.timeline(pid)
        b = cat.boundaries.get(pid)
        eng = TwinEngine("parity", 1, cat.meta(pid), serving, event_def, b, b.train_end if b is not None else -np.inf)
        raw: dict[tuple[float, int], float] = {}
        raw_captured = capture_raw(eng, raw) and raw_captured
        online: dict[tuple[float, int], float] = {}
        clock = tl.start
        while clock < tl.end - 1e-6:
            clock = min(clock + DAY, tl.end)
            for f in eng.advance(tl.released(clock), clock):
                for e in f["estimates"]:
                    if e["predicted_mg_dl"] is not None:
                        online[(round(f["_origin"], 6), int(e["horizon_minutes"]))] = float(e["predicted_mg_dl"])
        keys = [(round(float(r.origin), 6), int(r.horizon)) for r in o.itertuples()]
        got = np.array([online.get(k, np.nan) for k in keys])
        got_raw = np.array([raw.get(k, np.nan) for k in keys])
        offv = o["predicted"].to_numpy(float)
        d, d_raw = np.abs(got - offv), np.abs(got_raw - offv)
        rows.append(pd.DataFrame({"horizon": o["horizon"].to_numpy(int), "d": d, "d_raw": d_raw}))
        miss = int(np.isnan(got).sum())
        per[pid] = {"compared": int(np.isfinite(d).sum()), "missing_online": miss,
                    "max_abs_diff": float(np.nanmax(d)) if np.isfinite(d).any() else None,
                    "raw_max_abs_diff": float(np.nanmax(d_raw)) if np.isfinite(d_raw).any() else None}
    allr = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame({"horizon": [], "d": [], "d_raw": []})

    def stats(r: pd.DataFrame) -> dict[str, Any]:
        d, dr = r["d"].to_numpy(float), r["d_raw"].to_numpy(float)
        fin, fr = d[np.isfinite(d)], dr[np.isfinite(dr)]
        return {"expected": int(len(r)), "compared": int(fin.size), "missing_online": int(np.isnan(d).sum()),
                "over_tolerance": int((fin > TOLERANCE + 1e-9).sum()),
                "max_abs_diff_mg_dl": float(fin.max()) if fin.size else None,
                "raw_max_abs_diff_mg_dl": float(fr.max()) if fr.size else None,
                "raw_exact_matches": int((fr == 0).sum())}

    tot = stats(allr)
    split_manifest = None
    try:
        from glucotwin.data.pipeline import dataset_store_dir
        from glucotwin.dataset import current_split_manifest

        sm = current_split_manifest(dataset_store_dir())
        split_manifest = json.loads(sm.read_text()).get("split_hash") if sm.exists() else None
    except Exception:  # identity is reported, never guessed
        split_manifest = None
    out = {
        "check": "online twin engine replay vs saved offline final-test predictions",
        "model_version": serving.model_version, "experiment_id": exp, "pipeline": label, "personalization": pers,
        "feature_set_id": manifest["feature_set_id"], "transform_fingerprint": manifest["transform_fingerprint"],
        "data_fingerprint": cfg.get("data_fingerprint"), "split_hash": cfg.get("split_hash"),
        "segment": "test", "horizons_minutes": horizons, "participants": len(per),
        "offline_forecasts": int(len(off)), "compared": tot["compared"], "missing_online": tot["missing_online"],
        "tolerance_mg_dl": TOLERANCE, "tolerance_basis": "API displays forecasts rounded to 0.1 mg/dL",
        "max_abs_diff_mg_dl": tot["max_abs_diff_mg_dl"], "over_tolerance": tot["over_tolerance"],
        "outcome": "pass" if tot["compared"] and tot["over_tolerance"] == 0 and tot["missing_online"] == 0 else "fail",
        "raw_max_abs_diff_mg_dl": tot["raw_max_abs_diff_mg_dl"] if raw_captured else None,
        "raw_exact_matches": tot["raw_exact_matches"] if raw_captured else None,
        "raw_basis": ("unrounded online value (population + correction, float64) vs saved float64 offline prediction; "
                      "informational, the outcome uses the display tolerance only"),
        "per_horizon": {str(int(h)): stats(r) for h, r in allr.groupby("horizon")},
        "scope": "candidate" if a.candidate else "registered serving model",
        "identity": {
            **source, "model_dir": shown(mdir), "model_dir_tree_sha256": tree_sha256(mdir),
            "serving_json_sha256": sha256_file(mdir / "serving.json"),
            "artifact_checksum_files": manifest.get("files"),
            "experiment_dir": shown(edir), "metrics_sha256": sha256_file(edir / "metrics.json"),
            "predictions_sha256": sha256_file(edir / "predictions.parquet"),
            "adaptation": cfg.get("adaptation"),
            "intervals": {k: cfg.get("intervals", {}).get(k) for k in ("method", "level", "quantiles_mg_dl",
                                                                        "calibrated_for")},
            "alerts": cfg.get("alerts"), "profile_gate": cfg.get("profile_gate"),
            "replay_split_hash": split_manifest,
            "replay_split_matches_model": (split_manifest == cfg.get("split_hash")) if split_manifest else None,
        },
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"), "revision": revision(),
        # fingerprint of the check itself, so verification code added after the checked revision is traceable too
        "check_script_sha256": sha256_file(Path(__file__)),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    if not a.candidate and a.output is None:
        # the committed public summary keeps its established aggregate-only shape (no local paths)
        public = {k: v for k, v in out.items() if k != "identity"}
    else:
        public = out
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.write_text(json.dumps({**out, "per_participant": per}, indent=1))
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(public, indent=1) + "\n")
    print(json.dumps(public, indent=1))
    return 0 if out["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
