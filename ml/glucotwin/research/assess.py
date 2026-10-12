"""Assessment stages: outer folds (internal) and the reserved external cohort. Each is opened ONCE.

Both stages only load frozen fold artifacts (``pipeline.json`` + checksum-verified bundles + calibration records) and
refuse to run if any freeze hash, bundle checksum or calibration identity differs. An already-opened assessment can
only be re-run with an explicit reason, which is logged and turns the result into an exploratory re-run.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import fingerprint
from glucotwin.models.population import PopulationBundle
from glucotwin.research import calibration, warnings
from glucotwin.research.common import Ctx, load_ctx
from glucotwin.research.develop import cal_identity, fold_dir, run_mode
from glucotwin.research.protocol import (
    FINAL,
    load_frozen,
    load_protocol,
    pipeline_freeze_hash,
    plans_of,
    research_dir,
)


class AssessmentError(RuntimeError):
    pass


def _lock(path: Path, reason: str | None, what: str) -> dict[str, Any]:
    if path.exists():
        if not reason:
            raise AssessmentError(f"The {what} was already opened ({json.loads(path.read_text())['opened_at']}). "
                                  "Re-running needs --reopen-reason and is then exploratory, not confirmatory.")
        doc = json.loads(path.read_text())
        doc.setdefault("reopened", []).append({"at": datetime.now(UTC).isoformat(timespec="seconds"), "reason": reason})
        path.write_text(json.dumps(doc, indent=1))
        return doc
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"opened_at": datetime.now(UTC).isoformat(timespec="seconds"), "what": what, "reopened": []}
    path.write_text(json.dumps(doc, indent=1))
    return doc


def load_pipeline(experiment_id: str, fold: str, track: str) -> dict[str, Any]:
    p = fold_dir(experiment_id, fold, track) / "pipeline.json"
    if not p.exists():
        raise AssessmentError(f"{fold}/{track} is not frozen; run `glucotwin research develop` first")
    pl = json.loads(p.read_text())
    fh = pipeline_freeze_hash(pl)
    if fh != pl["freeze_hash"]:
        raise AssessmentError(f"{fold}/{track}: frozen pipeline was modified after freezing")
    return pl


def load_bundle(experiment_id: str, pl: dict[str, Any], label: str) -> PopulationBundle:
    meta = pl["bundles"][label]
    b = PopulationBundle.load(research_dir(experiment_id) / meta["dir"])  # verifies every file checksum
    if fingerprint(b.meta["files"]) != meta["hash"]:
        raise AssessmentError(f"{label}: bundle hash differs from the frozen record")
    return b


def predict_pipelines(ctx: Ctx, pl: dict[str, Any], rows: np.ndarray, partition: str, fold: str
                      ) -> tuple[pd.DataFrame, dict[str, dict[int, np.ndarray]], dict[str, float]]:
    """Predictions of every frozen (pipeline, mode) on ``rows`` with both interval methods."""
    frames, finals, latency = [], {}, {}
    t = ctx.t
    for label, meta in pl["bundles"].items():
        b = load_bundle(ctx.experiment_id, pl, label)
        sample = t[rows].iloc[: min(int(rows.sum()), 1000)]
        latency[label] = b.measure_latency_ms_per_1k(sample) if len(sample) else None
        pop = {h: np.where(rows & ctx.issued, p, np.nan) for h, p in b.predict(t).items()}
        for mname, mode in pl["modes"][label].items():
            final, corr, nres = run_mode(ctx, rows & ctx.issued, pop, mode)
            cal = pl["calibration"][f"{label}|{mname}"]
            calibration.check_compatible(cal, cal_identity(ctx, label, mname, mode, meta["hash"], pl["fold"],
                                                           meta["feature_set"]))
            iv = calibration.intervals(t, rows & ctx.issued, final, cal, ctx.horizons, ctx.td.tolerance)
            finals[f"{label}|{mname}"] = final
            for h in ctx.horizons:
                m = rows
                frames.append(pd.DataFrame({
                    "fold": fold, "partition": partition, "track": ctx.track, "dataset_id": ctx.td.dataset_id,
                    "patient_id": ctx.pids[m], "recording_id": t["recording_id"].to_numpy()[m],
                    "origin": t["origin"].to_numpy()[m], "data_cutoff": t["origin"].to_numpy()[m],
                    "elapsed_min": t["elapsed_min"].to_numpy()[m], "g_last": t["g_last"].to_numpy()[m],
                    "quality": t["quality"].to_numpy()[m], "horizon": h, "pipeline": label, "mode": mname,
                    "population": pop[h][m], "correction": corr[h][m], "final": final[h][m],
                    "residuals_matured": nres[h][m], "target": ctx.target(h)[m],
                    "target_at": t[f"target_{h}_at"].to_numpy()[m],
                    "lower_global": iv["global"][h][0][m], "upper_global": iv["global"][h][1][m],
                    "lower_cls": iv["cls"][h][0][m], "upper_cls": iv["cls"][h][1][m],
                    "cls_fallback": iv["cls_fallback"][h][m]}))
    return pd.concat(frames, ignore_index=True), finals, latency


def _events(ctx: Ctx, pl: dict[str, Any], rows: np.ndarray, finals: dict, fold: str) -> tuple[list[dict], list[dict]]:
    w = ctx.proto["warnings"]
    out, episodes = [], []
    for _key, wv in pl["warnings"].items():
        lab, mname, H = wv["pipeline"], wv["mode"], int(wv["horizon"])
        final = finals[f"{lab}|{mname}"]
        sc = warnings.scores(final, H)
        policies = {"primary": wv["primary"]["threshold"], "f1_comparator": wv["f1_comparator"]["threshold"],
                    **{f"budget_{b}": v["threshold"] for b, v in wv["sensitivity"].items()}}
        if "v2_fixed_threshold" in wv:
            policies["v2_fixed"] = wv["v2_fixed_threshold"]
        for pname, th in policies.items():
            if th is None:
                out.append({"fold": fold, "pipeline": lab, "mode": mname, "horizon": H, "policy": pname,
                            "threshold": None, "status": "no_feasible_threshold"})
                continue
            s, per = warnings.evaluate(ctx.t, rows, ctx.issued, sc, H, float(th), float(w["episode_merge_minutes"]),
                                       ctx.td.cadence)
            out.append({"fold": fold, "pipeline": lab, "mode": mname, "horizon": H, "policy": pname, "status": "ok", **s})
            if pname == "primary" and H == int(w["serving_horizon_minutes"]):
                for pid, res in per.items():
                    for ep in res.episodes:
                        episodes.append({"fold": fold, "pipeline": lab, "mode": mname, "patient_id": pid,
                                         **{k: v for k, v in ep.items() if k != "firing_times"},
                                         "firings": len(ep["firing_times"])})
        # descriptive full curve on the assessment rows (never used for any choice)
        for th in w["threshold_grid"]:
            s, _ = warnings.evaluate(ctx.t, rows, ctx.issued, sc, H, float(th), float(w["episode_merge_minutes"]),
                                     ctx.td.cadence)
            out.append({"fold": fold, "pipeline": lab, "mode": mname, "horizon": H, "policy": f"grid_{th}",
                        "status": "ok", **s})
    return out, episodes


def assess_internal(experiment_id: str, reopen_reason: str | None = None) -> dict[str, Any]:
    doc = load_frozen(experiment_id)
    root = research_dir(experiment_id) / "assessment"
    plans = [p for p in plans_of(doc) if p.fold != FINAL]
    pls = {(t, p.fold): load_pipeline(experiment_id, p.fold, t) for t in ("multimodal_5min", "portable_15min")
           for p in plans}  # every fold frozen before anything is opened
    lock = _lock(root / "opened.json", reopen_reason, "internal outer-fold assessment")
    t0 = time.perf_counter()
    frames, events, episodes, lat = [], [], [], {}
    for track in ("multimodal_5min", "portable_15min"):
        ctx = load_ctx(track, "development", experiment_id)
        for p in plans:
            pl = pls[(track, p.fold)]
            rows = ctx.rows(p.assessment)
            df, finals, latency = predict_pipelines(ctx, pl, rows, "outer_assessment", p.fold)
            frames.append(df)
            lat[f"{track}|{p.fold}"] = latency
            if ctx.proto["tracks"][track].get("events"):
                ev, eps = _events(ctx, pl, rows, finals, p.fold)
                events += [{"track": track, **e} for e in ev]
                episodes += [{"track": track, **e} for e in eps]
    preds = pd.concat(frames, ignore_index=True)
    preds.to_parquet(root / "predictions.parquet", index=False)
    (root / "events.json").write_text(json.dumps({"events": events, "primary_episodes_60": episodes}, indent=1,
                                                 default=_jd))
    pkg = package_candidates(experiment_id)
    for track in pkg:
        pkg[track]["parity"] = parity_check(experiment_id, track)
    summary = {"experiment_id": experiment_id, "opened": lock, "rows": int(len(preds)),
               "participants": int(preds["patient_id"].nunique()), "inference_ms_per_1k": lat,
               "seconds": time.perf_counter() - t0, "candidates": pkg,
               "predictions_sha256": _sha(root / "predictions.parquet")}
    (root / "summary.json").write_text(json.dumps(summary, indent=1, default=_jd))
    return {k: v for k, v in summary.items() if k != "inference_ms_per_1k"}


def assess_external(experiment_id: str, reopen_reason: str | None = None) -> dict[str, Any]:
    doc = load_frozen(experiment_id)
    track = "portable_15min"
    pl = load_pipeline(experiment_id, FINAL, track)
    cand_dir = research_dir(experiment_id) / "candidates" / track
    if not (cand_dir / "candidate.json").exists():
        raise AssessmentError("Portable deployment candidate is not packaged; run `glucotwin research assess` first")
    cand = json.loads((cand_dir / "candidate.json").read_text())
    root = research_dir(experiment_id) / "external"
    lock = _lock(root / "opened.json", reopen_reason, "reserved ShanghaiT2DM external assessment")
    t0 = time.perf_counter()
    ctx = load_ctx(track, "external", experiment_id)
    if sorted(ctx.t["patient_id"].unique()) != sorted(doc["external_participants"]):
        raise AssessmentError("External participants differ from the frozen membership")
    rows = np.ones(len(ctx.t), dtype=bool)
    df, _finals, latency = predict_pipelines(ctx, pl, rows, "external", FINAL)
    df.to_parquet(root / "predictions.parquet", index=False)
    summary = {"experiment_id": experiment_id, "opened": lock, "candidate": cand["selected"],
               "candidate_freeze_hash": pl["freeze_hash"], "participants": int(df["patient_id"].nunique()),
               "rows": int(len(df)), "decimation": ctx.td.meta.get("decimation"), "inference_ms_per_1k": latency,
               "seconds": time.perf_counter() - t0, "predictions_sha256": _sha(root / "predictions.parquet")}
    (root / "summary.json").write_text(json.dumps(summary, indent=1, default=_jd))
    return {k: v for k, v in summary.items() if k != "inference_ms_per_1k"}


# ------------------------------------------------------------------------------------------------ deployment candidates


def package_candidates(experiment_id: str) -> dict[str, Any]:
    """Bundle the final fold's selected pipeline of each track (weights, transformation, adaptation, ranges, warning
    policy) in the serving artifact format. Packaging never touches the registry."""
    out = {}
    for track in ("multimodal_5min", "portable_15min"):
        pl = load_pipeline(experiment_id, FINAL, track)
        label = pl["selection"]["selected"]
        meta = pl["bundles"][label]
        modes = pl["modes"][label]
        final_mode = modes.get("final")
        mode_name = "final" if "final" in modes else "off"
        cal = pl["calibration"][f"{label}|{mode_name}"]
        src = research_dir(experiment_id) / meta["dir"]
        dest = research_dir(experiment_id) / "candidates" / track
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        exp = pl["experiment_id"]
        model_version = f"{meta['family']}.{meta['feature_set']}.{exp}"
        proto = load_protocol(exp)
        ad = proto["adaptation"]
        pol = {"policy_id": ad["policy_id"], "enabled": final_mode is not None,
               "shrinkage_k": float(final_mode["k"]) if final_mode else float(ad["v2_policy"]["shrinkage_k"]),
               "half_life_minutes": float(final_mode["half_life"]) if final_mode else float(ad["v2_policy"]["half_life_minutes"]),
               "cap_mg_dl": float(ad["cap_mg_dl"]), "min_residuals": int(ad["min_residuals"]),
               "reset_gap_minutes": float(ad["reset_gap_minutes"]),
               "match_tolerance_minutes": float(ad["match_tolerance_minutes"][track]),
               "target_wait_minutes": float(ad["target_wait_minutes"])}
        H = int(proto["warnings"]["serving_horizon_minutes"])
        wkey = f"{label}|final|{H}"
        thr = pl["warnings"].get(wkey, {}).get("primary", {}).get("threshold") if proto["tracks"][track].get("events") else None
        serving = {
            "model_version": model_version, "model_family": meta["family"], "feature_set_id": meta["feature_set"],
            "experiment_id": exp, "candidate_of_track": track, "status": "candidate_not_promoted",
            "selection_rationale": pl["selection"]["rationale"], "freeze_hash": pl["freeze_hash"],
            "adaptation": pol,
            "adaptation_collect_rule": "all origins of a replayed participant (new-participant setting)",
            "intervals": {"method": "split-conformal absolute residuals of the final adapted pipeline, pooled over "
                                    "reserved calibration participants, per horizon",
                          "level": cal["level"], "quantiles_mg_dl": {h: v["global_q"] for h, v in cal["horizons"].items()},
                          "calibrated_for": f"{label} personalization={mode_name}", "identity_hash": cal["identity_hash"],
                          "calibration_participants": pl["plan"]["calibration"]},
            "alerts": ({"rule_version": "new-high-warning-v2-workload", "policy_id": f"{exp}:workload-2.0",
                        "horizon_minutes": H, "threshold_margin_mg_dl": thr, "score_kind": "forecast_margin_mg_dl",
                        "episode_merge_minutes": float(proto["warnings"]["episode_merge_minutes"]),
                        "experiment_id": exp, "selection": pl["warnings"].get(wkey, {}).get("primary")}
                       if proto["tracks"][track].get("events") else {}),
            "event_definition": proto["warnings"]["event"], "frozen_at": pl["frozen_at"], "synthetic_fitted": False,
            "trained_on": {"dataset": "cgmacros", "development_participants": pl["plan"]["development"]},
        }
        (dest / "serving.json").write_text(json.dumps(serving, indent=2, default=_jd))
        files = {p.name: _sha(p) for p in sorted(dest.iterdir()) if p.is_file() and p.name != "candidate.json"}
        cand = {"track": track, "selected": label, "mode": mode_name, "model_version": model_version,
                "freeze_hash": pl["freeze_hash"], "files_sha256": files, "packaged_at": datetime.now(UTC).isoformat(
                    timespec="seconds"), "serving_eligible": bool(proto["tracks"][track].get("serving_eligible"))}
        (dest / "candidate.json").write_text(json.dumps(cand, indent=2))
        out[track] = {"selected": label, "mode": mode_name, "model_version": model_version, "threshold": thr}
    return out


def parity_check(experiment_id: str, track: str) -> dict[str, Any]:
    """Replay one development participant through the ONLINE engine with the packaged candidate and compare population
    prediction, patient correction and final forecast with the OFFLINE research path before display rounding."""
    import glucotwin.twin as twin
    from glucotwin.research.common import development_store
    from glucotwin.research.tables import decimate_patient, event_definition
    from glucotwin.serving import ServingModel

    d = research_dir(experiment_id) / "candidates" / track
    cand = json.loads((d / "candidate.json").read_text())
    serving_cfg = json.loads((d / "serving.json").read_text())
    serving = ServingModel(cand["model_version"], PopulationBundle.load(d), serving_cfg, d)
    pl = load_pipeline(experiment_id, FINAL, track)
    pid = pl["plan"]["development"][0]
    proto = load_protocol(experiment_id)
    pdata = development_store().load(pid)
    if track == "portable_15min":
        pdata, _ = decimate_patient(pdata, float(proto["tracks"][track]["cadence_minutes"]))
    ctx = load_ctx(track, "development", experiment_id, participants=[pid])
    rows = ctx.issued.copy()
    pop = {h: np.where(rows, p, np.nan) for h, p in serving.bundle.predict(ctx.t).items()}
    mode = pl["modes"][cand["selected"]].get(cand["mode"])
    final, corr, _ = run_mode(ctx, rows, pop, mode)
    end = float(ctx.t["origin"].max())
    original_r = twin._r
    twin._r = lambda x, nd=1: (None if x is None else float(x))  # compare BEFORE display rounding
    try:
        eng = twin.TwinEngine("parity", 1, pdata.meta, serving, event_definition(proto), None, -np.inf)
        t0 = time.perf_counter()
        fcs = eng.advance(pdata, end)
        secs = time.perf_counter() - t0
    finally:
        twin._r = original_r
    by_origin = {round(f["_origin"], 6): f for f in fcs}
    dp = dc = df_ = 0.0
    n = 0
    fired_on = fired_off = 0
    thr = (serving_cfg.get("alerts") or {}).get("threshold_margin_mg_dl")
    from glucotwin.research.warnings import scores
    sc = scores(final, int((serving_cfg.get("alerts") or {}).get("horizon_minutes", 60))) if thr is not None else None
    elig = ctx.t["ew_eligible"].to_numpy(bool) if "ew_eligible" in ctx.t else None
    for i, o in enumerate(ctx.t["origin"].to_numpy(float)):
        f_ = by_origin.get(round(o, 6))
        if f_ is None or not rows[i]:
            continue
        for e in f_["estimates"]:
            h = int(e["horizon_minutes"])
            comp = e["components"] or {}
            if comp.get("population_mg_dl") is None:
                continue
            dp = max(dp, abs(comp["population_mg_dl"] - pop[h][i]))
            dc = max(dc, abs((comp["patient_correction_mg_dl"] or 0.0) - corr[h][i]))
            df_ = max(df_, abs(e["predicted_mg_dl"] - final[h][i]))
        n += 1
        if thr is not None:
            fired_on += int(any(r["alert_fired"] for r in f_["event_risk"]))
            fired_off += int(bool(elig[i]) and np.isfinite(sc[i]) and sc[i] >= thr)
    out = {"participant_role": "first development participant of the final candidate (in-sample; parity only)",
           "origins": n, "max_abs_population": float(dp), "max_abs_correction": float(dc), "max_abs_final": float(df_),
           "tolerance": 1e-6, "passed": bool(n > 0 and max(dp, dc, df_) <= 1e-6),
           "warning_firings_online": fired_on, "warning_firings_offline": fired_off,
           "ms_per_origin": round(1000 * secs / max(1, len(fcs)), 3),
           "latency_note": "end-to-end engine time per forecast origin (features, prediction, adaptation, ranges, "
                           "warnings, explanations); excludes HTTP"}
    (d / "parity.json").write_text(json.dumps(out, indent=1))
    return out


def _sha(path: Path) -> str:
    from glucotwin.config import file_sha256
    return file_sha256(path)


def _jd(o):
    from glucotwin.research.develop import _jd as j
    return j(o)
