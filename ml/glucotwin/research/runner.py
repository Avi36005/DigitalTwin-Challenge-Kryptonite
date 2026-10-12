"""Stage orchestration for ``glucotwin research ...``. Never imports or writes the model registry.

    freeze     write split membership once (artifacts/research/<id>/splits.json)
    smoke      development-only timing on one inner split of outer fold 1 (budget evidence)
    develop    inner CV, selection, adaptation, thresholds, refit, calibration, freeze — per fold and track
    assess     outer-fold assessment, once, from frozen fold artifacts
    external   reserved external cohort, once, with the frozen portable deployment candidate
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from glucotwin.research.protocol import (
    DEFAULT_EXPERIMENT,
    FINAL,
    freeze,
    load_frozen,
    load_protocol,
    plans_of,
    research_dir,
)

TRACKS = ("multimodal_5min", "portable_15min")


def do_freeze(experiment_id: str = DEFAULT_EXPERIMENT) -> dict[str, Any]:
    from glucotwin.config import paths
    from glucotwin.data import inventory
    from glucotwin.research.common import (
        V2_MODEL_DIR,
        development_ids,
        development_store,
        external_ids,
        external_store,
        source_keys,
        store_fingerprint,
    )
    from glucotwin.research.protocol import ProtocolError, check_required_sources

    proto = load_protocol(experiment_id)
    inv = inventory.build()
    check_required_sources(proto, {d["dataset_id"]: d["access_status"] for d in inv["datasets"]})
    if not (paths().root / V2_MODEL_DIR / "manifest.json").exists():
        raise ProtocolError(f"The v2 recipe comparator needs {V2_MODEL_DIR}; run `make data` and `make experiment` first.")
    dev, ext = development_store(), external_store()
    ov = inv["overlap_check"]
    if ov["flagged_pairs"]:
        raise RuntimeError(f"Overlapping recordings across sources: {ov['flagged_pairs'][:3]}; resolve before freezing")
    doc = freeze(experiment_id, development_ids(dev), external_ids(ext),
                 {"cgmacros": store_fingerprint(dev), "shanghai_t2dm": store_fingerprint(ext)},
                 extra={"overlap_check": ov},
                 keys=source_keys() if proto["folds"].get("assignment_key") == "source_participant_key" else None)
    return {k: doc[k] for k in ("experiment_id", "protocol_hash", "split_hash", "frozen_at", "counts_by_dataset")}


def do_smoke(experiment_id: str = DEFAULT_EXPERIMENT) -> dict[str, Any]:
    """One inner fit per tree configuration, feature set and horizon on outer fold 1's first inner split."""
    from glucotwin.features import FEATURE_SETS
    from glucotwin.research.common import development_ids, development_store, load_ctx
    from glucotwin.research.develop import TREE_CONFIGS, _fit_tree
    from glucotwin.research.models import sample_trials
    from glucotwin.research.protocol import make_plans

    proto = load_protocol(experiment_id)
    ids = development_ids(development_store())
    plan = make_plans(ids, proto["folds"], int(proto["random_seed"]))[0]
    train = [p for p in plan.development if p not in plan.inner[0]]
    out: dict[str, Any] = {"experiment_id": experiment_id, "fold": plan.fold, "train_participants": len(train),
                           "note": "development participants only; no assessment, calibration or external data loaded",
                           "fits": []}
    s = proto["models"]["search"]
    for track in TRACKS:
        t0 = time.perf_counter()
        ctx = load_ctx(track, "development", experiment_id, participants=list(plan.development))
        out[f"table_seconds_{track}"] = time.perf_counter() - t0
        for config in TREE_CONFIGS:
            fam = proto["models"]["trees"][config]["family"]
            for fs in proto["tracks"][track]["feature_sets"]:
                for h in ctx.horizons:
                    params = sample_trials(s[f"{fam}_space"], fam, 1, [ctx.seed, 0 if fam == "lightgbm" else 1, h,
                                                                          list(FEATURE_SETS).index(fs)])[0]
                    _, info = _fit_tree(ctx, config, fs, params, train, h, ctx.seed)
                    out["fits"].append({"track": track, "config": config, "feature_set": fs, "horizon": h,
                                        "seconds": info["fit_seconds"], "best_iteration": info["best_iteration"]})
    folds = len(make_plans(ids, proto["folds"], int(proto["random_seed"])))
    inner, trials = int(proto["folds"]["inner_folds"]), int(s["trials_per_config"])
    total = sum(f["seconds"] for f in out["fits"]) * inner * trials * folds
    out["estimated_tree_fit_seconds_serial"] = total
    out["estimated_fits"] = len(out["fits"]) * inner * trials * folds
    out["budget_decision"] = (f"Declared budget ({trials} trials, {s['max_boosting_rounds']} rounds, patience "
                              f"{s['early_stopping_rounds']}) kept: estimated {total / 60:.0f} CPU-minutes of tree fits.")
    out["created_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    path = research_dir(experiment_id) / "smoke.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return {k: v for k, v in out.items() if k != "fits"}


def _develop_job(experiment_id: str, track: str, fold: str) -> dict[str, Any]:
    from glucotwin.research.common import load_ctx
    from glucotwin.research.develop import develop

    doc = load_frozen(experiment_id)
    plan = next(p for p in plans_of(doc) if p.fold == fold)
    ctx = load_ctx(track, "development", experiment_id, participants=sorted(set(plan.development) | set(plan.calibration)))
    log_path = research_dir(experiment_id) / "logs" / f"develop_{fold}_{track}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as fh:
        def log(msg: str) -> None:
            fh.write(msg + "\n")
            fh.flush()
        res = develop(ctx, plan, log=log)
    return {"fold": fold, "track": track, "selected": res["selection"]["selected"], "freeze_hash": res["freeze_hash"],
            "seconds": res["timings_seconds"]["total"]}


def do_develop(experiment_id: str = DEFAULT_EXPERIMENT, workers: int | None = None, tracks=TRACKS,
               folds: list[str] | None = None) -> list[dict[str, Any]]:
    doc = load_frozen(experiment_id)
    jobs = [(t, p.fold) for t in tracks for p in plans_of(doc) if folds is None or p.fold in folds]
    results = []
    if workers == 0:  # in-process, sequential (tests and debugging)
        for t, f in jobs:
            results.append(_develop_job(experiment_id, t, f))
        return results
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 4) // 2))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_develop_job, experiment_id, t, f): (t, f) for t, f in jobs}
        for fut in as_completed(futs):
            r = fut.result()
            print(json.dumps(r), flush=True)
            results.append(r)
    return results


def do_assess(experiment_id: str = DEFAULT_EXPERIMENT, reason: str | None = None) -> dict[str, Any]:
    from glucotwin.research.assess import assess_internal

    return assess_internal(experiment_id, reason)


def do_external(experiment_id: str = DEFAULT_EXPERIMENT, reason: str | None = None) -> dict[str, Any]:
    from glucotwin.research.assess import assess_external

    return assess_external(experiment_id, reason)


__all__ = ["do_freeze", "do_smoke", "do_develop", "do_assess", "do_external", "FINAL"]
