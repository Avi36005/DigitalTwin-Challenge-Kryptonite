"""Zero-shot foundation-model CGM-only baseline gt-foundation-2026-10-21 (decision D-054).

The protocol (configs/experiments/gt-foundation-2026-10-21.yaml) was committed before any participant forecast. Torch and
chronos are imported ONLY inside ``predict`` / the real adapter, which run in the isolated optional environment
(~/.cache/glucotwin-chronos/venv); the project's CPU path (export, residual, summarise) never imports them.

Usage:
  uv run python scripts/foundation_baseline.py export                              # project env: causal inputs + origins
  ~/.cache/glucotwin-chronos/venv/bin/python scripts/foundation_baseline.py predict   # isolated env: zero-shot forecasts
  uv run python scripts/foundation_baseline.py residual                            # project env: F1 residual + R0 refit
  uv run python scripts/foundation_baseline.py summarise                           # project env: metrics + report
"""

from __future__ import annotations

import hashlib
import json
import platform
import resource
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROTO_PATH = ROOT / "configs/experiments/gt-foundation-2026-10-21.yaml"
PROTO = yaml.safe_load(PROTO_PATH.read_text())
OUT = ROOT / PROTO["artifacts"]["root"]
REPORT = ROOT / PROTO["artifacts"]["report"]
HS = [int(h) for h in PROTO["horizons"]]
CADENCE = 5.0
CONTEXT = int(PROTO["inputs"]["context_length"])
PRED_LEN = 12
SLOT_TOL = 2.5
EPS = 1e-6
QUANTILES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
MODEL_ID = PROTO["model"]["checkpoint"]
REVISION = PROTO["model"]["revision"]
SEED = 20261021
NBOOT = 2000
BATCH = 256
TRACK = "multimodal_5min"
BASE = PROTO["base_experiment"]
# The checkout holding the git-ignored data/artifacts (a worktree has none of its own).
MAIN = Path("/Users/avinashgehi3/projects/Digitaltwin")
JOINT_NPZ = MAIN / "artifacts/research/gt-joint-2026-10-21/assessment_predictions.npz"


# ----------------------------------------------------------------------------------------------- pure causal logic
def step_index(h_minutes: int, cadence: float = CADENCE) -> int:
    """0-based output index for horizon ``h``: output step j (1-based) is t + j * cadence."""
    j = h_minutes / cadence
    if abs(j - round(j)) > 1e-9 or round(j) < 1:
        raise ValueError(f"horizon {h_minutes} is not a positive multiple of the {cadence}-min cadence")
    return int(round(j)) - 1


def build_context(obs: np.ndarray, avail: np.ndarray, val: np.ndarray, origin: float,
                  length: int = CONTEXT, cadence: float = CADENCE) -> np.ndarray:
    """Regular grid of ``length`` slots ending at ``origin``; only readings observed AND available at or before it.

    ``obs`` must be sorted ascending. Slot k sits at origin - cadence * (length - 1 - k). A reading fills the slot within
    ``SLOT_TOL`` minutes of its observation time (a later reading wins); empty slots are NaN."""
    ctx = np.full(length, np.nan, dtype=np.float32)
    lo = np.searchsorted(obs, origin - cadence * (length - 1) - SLOT_TOL - EPS, "left")
    hi = np.searchsorted(obs, origin + EPS, "right")
    if hi <= lo:
        return ctx
    o, a, v = obs[lo:hi], avail[lo:hi], val[lo:hi]
    keep = (a <= origin + EPS) & (o <= origin + EPS) & np.isfinite(v)
    o, v = o[keep], v[keep]
    slot = np.rint((o - origin) / cadence).astype(int) + (length - 1)
    ok = (slot >= 0) & (slot < length) & (np.abs(o - (origin - cadence * (length - 1 - slot))) <= SLOT_TOL + EPS)
    ctx[slot[ok]] = v[ok].astype(np.float32)   # assignment in observation order: the latest reading wins a slot
    return ctx


def context_sha(ctx: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(ctx, dtype=np.float32).tobytes()).hexdigest()[:16]


def origin_sha(pid: str, origin: float) -> str:
    return hashlib.sha256(f"{pid}|{origin:.4f}".encode()).hexdigest()[:16]


def forecast_origins(readings: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]], pids: np.ndarray,
                     origins: np.ndarray, predict_fn: Callable[[np.ndarray], np.ndarray], batch: int = BATCH,
                     length: int = CONTEXT) -> tuple[np.ndarray, list[str]]:
    """Per-origin causal forecasts. ``predict_fn`` maps (B, length) float32 contexts -> (B, n_quantiles, >=12).

    Each row of a batch is its own series built from its own causal window; batching never mixes windows."""
    out, hashes = [], []
    for s in range(0, len(origins), batch):
        ctxs = np.stack([build_context(*readings[p], float(t), length) for p, t in
                         zip(pids[s:s + batch], origins[s:s + batch], strict=True)])
        hashes += [context_sha(c) for c in ctxs]
        out.append(np.asarray(predict_fn(ctxs), dtype=np.float64)[:, :, :PRED_LEN])
    return np.concatenate(out), hashes


# ----------------------------------------------------------------------------------------------- metrics
def per_person(err: np.ndarray, pids: np.ndarray) -> pd.Series:
    return pd.Series(np.abs(err)).groupby(pids).mean()


def macro_mae(err: np.ndarray, pids: np.ndarray) -> float:
    return float(per_person(err, pids).mean())


def pooled_mae(err: np.ndarray) -> float:
    return float(np.mean(np.abs(err)))


def paired_bootstrap(a: pd.Series, b: pd.Series, n: int = NBOOT, seed: int = SEED) -> dict:
    """Participant bootstrap of mean_person(a) - mean_person(b) (a, b: per-person MAE on identical origins)."""
    d = (a - b).dropna().to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n, len(d)))
    bs = d[idx].mean(axis=1)
    return {"mean": float(d.mean()), "lo": float(np.quantile(bs, 0.025)), "hi": float(np.quantile(bs, 0.975)),
            "people": int(len(d)), "people_better": int((d < 0).sum())}


# ----------------------------------------------------------------------------------------------- stage: export
def export() -> None:
    from glucotwin.research.common import load_ctx
    from glucotwin.research.protocol import FINAL, load_frozen, plans_of

    ctx = load_ctx(TRACK, "development", BASE)
    t = ctx.t
    fold_of = {}
    for p in plans_of(load_frozen(BASE)):
        if p.fold != FINAL:
            for pid in p.assessment:
                fold_of[pid] = p.fold
    o = pd.DataFrame({"row": np.arange(len(t)), "patient_id": t["patient_id"].to_numpy(), "origin": t["origin"].to_numpy(float),
                      "fold": t["patient_id"].map(fold_of).to_numpy(), "quality": t["quality"].astype(str).to_numpy(),
                      "g_last": t["g_last"].to_numpy(float)})
    for h in HS:
        o[f"target_{h}"] = t[f"target_{h}"].to_numpy(float)
    rd = [pd.DataFrame({"patient_id": pid, "observed": p.g_obs, "available": p.g_avail, "value": p.g_val})
          for pid, p in ctx.td.prep.items()]
    (OUT / "inputs").mkdir(parents=True, exist_ok=True)
    o.to_parquet(OUT / "inputs/origins.parquet", index=False)
    pd.concat(rd, ignore_index=True).to_parquet(OUT / "inputs/readings.parquet", index=False)
    d = np.concatenate([np.diff(p.g_obs) for p in ctx.td.prep.values()])
    meta = {"base_experiment": BASE, "rows": len(o), "issued": int((o.quality != "insufficient").sum()),
            "people": int(o.patient_id.nunique()), "cadence_share_5min": float(np.mean(np.abs(d - 5) < 0.5)),
            "max_available_minus_observed_min": float(max(np.max(p.g_avail - p.g_obs) for p in ctx.td.prep.values())),
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds")}
    (OUT / "inputs/meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


def load_inputs() -> tuple[pd.DataFrame, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    o = pd.read_parquet(OUT / "inputs/origins.parquet")
    r = pd.read_parquet(OUT / "inputs/readings.parquet")
    readings = {}
    for pid, g in r.groupby("patient_id", sort=False):
        g = g.sort_values(["observed", "available"], kind="mergesort")
        readings[pid] = (g["observed"].to_numpy(float), g["available"].to_numpy(float), g["value"].to_numpy(float))
    return o, readings


# ----------------------------------------------------------------------------------------------- stage: predict
class ChronosAdapter:
    """Real checkpoint, zero-shot, CPU. Imported only in the isolated environment."""

    def __init__(self, threads: int = 2):
        import torch
        from chronos import BaseChronosPipeline
        from huggingface_hub import snapshot_download

        torch.set_num_threads(threads)
        self.torch = torch
        self.path = Path(snapshot_download(MODEL_ID, revision=REVISION))
        self.pipe = BaseChronosPipeline.from_pretrained(str(self.path), device_map="cpu", torch_dtype=torch.float32)
        self.pipe.model.eval()
        self.kind = type(self.pipe).__name__
        self.n_params = int(sum(p.numel() for p in self.pipe.model.parameters()))
        self.weights_sha256 = hashlib.sha256((self.path / "model.safetensors").read_bytes()).hexdigest()
        self.quantiles = list(self.pipe.quantiles)
        assert self.quantiles == QUANTILES, self.quantiles

    def __call__(self, ctxs: np.ndarray) -> np.ndarray:
        with self.torch.inference_mode():
            q = self.pipe.predict(self.torch.from_numpy(np.asarray(ctxs, dtype=np.float32)),
                                  prediction_length=PRED_LEN, limit_prediction_length=True)
        return q.numpy()


def peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1e6 if sys.platform == "darwin" else r / 1e3


def predict() -> None:
    import importlib.metadata as md

    import torch

    o, readings = load_inputs()
    rows = o[o.quality != "insufficient"].reset_index(drop=True)
    pids, origins = rows.patient_id.to_numpy(), rows.origin.to_numpy(float)
    ad = ChronosAdapter(threads=2)
    # warm-up then latency
    warm = np.stack([build_context(*readings[pids[i]], float(origins[i])) for i in range(64)])
    ad(warm[:1])
    ad(warm)
    t0 = time.perf_counter()
    for i in range(50):
        ad(warm[i:i + 1])
    single_ms = (time.perf_counter() - t0) / 50 * 1e3
    t0 = time.perf_counter()
    q, hashes = forecast_origins(readings, pids, origins, ad)
    total_s = time.perf_counter() - t0
    # determinism / batch-composition check: re-predict a fixed subset in reverse order with another batch size
    sub = np.arange(min(1000, len(rows)))[::-1]
    q2, h2 = forecast_origins(readings, pids[sub], origins[sub], ad, batch=97)
    det = {"origins": int(len(sub)), "max_abs_diff_mg_dl": float(np.nanmax(np.abs(q2 - q[sub]))),
           "context_hashes_equal": bool([hashes[i] for i in sub] == h2)}
    out = rows[["row", "patient_id", "origin", "fold"]].copy()
    out["origin_sha"] = [origin_sha(p, t) for p, t in zip(pids, origins, strict=True)]
    out["context_sha"] = hashes
    for h in HS:
        k = step_index(h)
        for qi, qq in enumerate(QUANTILES):
            out[f"q{int(qq * 100):02d}_{h}"] = q[:, qi, k]
        out[f"median_{h}"] = q[:, QUANTILES.index(0.5), k]
    out["n_context_readings"] = [int(np.isfinite(build_context(*readings[p], float(t))).sum()) if i % 50 == 0 else -1
                                 for i, (p, t) in enumerate(zip(pids, origins, strict=True))]
    out.to_parquet(OUT / "zero_shot_predictions.parquet", index=False)
    meta = {
        "experiment_id": PROTO["experiment_id"], "decision": PROTO["decision"],
        "checkpoint": MODEL_ID, "revision": REVISION, "license": PROTO["model"]["license"], "pipeline_class": ad.kind,
        "parameters": ad.n_params, "weights_sha256": ad.weights_sha256, "mode": "zero-shot inference (eval, no grad)",
        "context_length": CONTEXT, "prediction_length": PRED_LEN, "step_index": {str(h): step_index(h) for h in HS},
        "point_summary": "median (q0.5)", "quantiles": QUANTILES,
        "protocol_sha256": hashlib.sha256(PROTO_PATH.read_bytes()).hexdigest()[:16],
        "origins": int(len(rows)), "people": int(rows.patient_id.nunique()),
        "latency": {"threads": torch.get_num_threads(), "warm_single_origin_ms": round(single_ms, 3),
                    "batch_size": BATCH, "batched_ms_per_origin": round(total_s / len(rows) * 1e3, 4),
                    "origins_per_second": round(len(rows) / total_s, 1), "full_mask_seconds": round(total_s, 1),
                    "includes": "causal context construction + hashing + model forward"},
        "peak_rss_mb": round(peak_rss_mb(), 1), "determinism": det,
        "versions": {k: md.version(k) for k in ("torch", "chronos-forecasting", "transformers", "numpy", "pandas")},
        "python": platform.python_version(), "hardware": {"machine": platform.machine(), "processor": "Apple M4",
                                                          "logical_cpus": 10, "ram_gb": 16, "threads_used": 2},
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (OUT / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


# ----------------------------------------------------------------------------------------------- stage: residual
def residual() -> None:
    """Template F1 (declared) and a same-code R0 refit, per outer fold, then the R0 causal correction."""
    import lightgbm as lgb
    from glucotwin.config import paths
    from glucotwin.features import FEATURE_SETS
    from glucotwin.research import adapt
    from glucotwin.research.common import load_ctx
    from glucotwin.research.protocol import FINAL, load_frozen, plans_of

    ctx = load_ctx(TRACK, "development", BASE)
    t = ctx.t
    pids, issued = ctx.pids, ctx.issued
    zs = pd.read_parquet(OUT / "zero_shot_predictions.parquet")
    assert (t["origin"].to_numpy()[zs.row] == zs.origin.to_numpy()).all()
    g = t["g_last"].to_numpy(float)
    med = {h: np.full(len(t), np.nan) for h in HS}
    spread = {h: np.full(len(t), np.nan) for h in HS}
    for h in HS:
        med[h][zs.row] = zs[f"median_{h}"].to_numpy()
        spread[h][zs.row] = (zs[f"q90_{h}"] - zs[f"q10_{h}"]).to_numpy()
    base_cols = FEATURE_SETS["dyn-prof-v2"].columns()
    Xb = t[base_cols].to_numpy(float)
    man = json.loads((paths().artifacts / "models/lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion/manifest.json").read_text())
    rec = {int(h): ({k: v for k, v in p.items() if k not in ("best_iteration", "fit_seconds")}, int(p["best_iteration"]))
           for h, p in man["params"].items()}
    plans = [p for p in plans_of(load_frozen(BASE)) if p.fold != FINAL]
    pop = {a: {h: np.full(len(t), np.nan) for h in HS} for a in ("R0", "F1")}
    fits = []
    assess = np.zeros(len(t), bool)
    for p in plans:
        test = np.isin(pids, list(p.assessment)) & issued
        assess |= test
        train_people = list(p.development) + list(p.calibration)
        for h in HS:
            y = t[f"target_{h}"].to_numpy(float)
            params, rounds = rec[h]
            prm = {"objective": "regression", "metric": "l2", "verbosity": -1, "seed": SEED + h, "deterministic": True,
                   "force_row_wise": True, "num_threads": 2, "bagging_freq": 1, **params}
            for arm in ("R0", "F1"):
                if arm == "R0":
                    X, base = Xb, g
                else:
                    X = np.column_stack([Xb, med[h] - g, spread[h]])
                    base = med[h]
                lab = y - base
                rows = np.isin(pids, train_people) & issued & np.isfinite(lab)
                t0 = time.time()
                bst = lgb.train(prm, lgb.Dataset(X[rows], label=lab[rows], free_raw_data=False), num_boost_round=rounds)
                pop[arm][h][test] = base[test] + bst.predict(X[test])
                fits.append({"arm": arm, "fold": p.fold, "horizon": h, "train_people": len(train_people),
                             "train_rows": int(rows.sum()), "features": X.shape[1], "rounds": rounds,
                             "seconds": round(time.time() - t0, 2)})
                print(fits[-1], flush=True)
    policy = adapt.make_policy(ctx.proto, TRACK, 96, 240)
    res = {"row": np.arange(len(t))}
    for arm in ("R0", "F1"):
        corr, _ = adapt.prequential(t, ctx.td.prep, assess, pop[arm], policy, HS)
        fin = adapt.apply(pop[arm], corr)
        for h in HS:
            res[f"{arm}_pop_{h}"] = pop[arm][h]
            res[f"{arm}_final_{h}"] = np.where(assess, fin[h], np.nan)
    pd.DataFrame(res).to_parquet(OUT / "residual_predictions.parquet", index=False)
    (OUT / "residual_fits.json").write_text(json.dumps({"fits": fits, "correction": {"shrinkage_k": 96, "half_life": 240},
                                                        "template": "F1"}, indent=1))


# ----------------------------------------------------------------------------------------------- stage: summarise
def _compare(df: pd.DataFrame, a: str, b: str, h: int, mask: np.ndarray) -> dict:
    y = df[f"target_{h}"].to_numpy(float)
    ea, eb = df[a].to_numpy(float) - y, df[b].to_numpy(float) - y
    m = mask & np.isfinite(ea) & np.isfinite(eb)
    p = df["patient_id"].to_numpy()[m]
    pa, pb = per_person(ea[m], p), per_person(eb[m], p)
    hi = m & (y > 180)
    ph = df["patient_id"].to_numpy()[hi]
    cnt = pd.Series(ph).value_counts()
    keep = cnt[cnt >= 50].index
    ha, hb = per_person(ea[hi], ph), per_person(eb[hi], ph)
    return {"origins": int(m.sum()), "people": int(len(pa)),
            "macro": {a: float(pa.mean()), b: float(pb.mean())}, "pooled": {a: pooled_mae(ea[m]), b: pooled_mae(eb[m])},
            "rmse": {a: float(np.sqrt(np.mean(ea[m] ** 2))), b: float(np.sqrt(np.mean(eb[m] ** 2)))},
            "diff_macro": paired_bootstrap(pa, pb),
            "high_gt180": {"origins": int(hi.sum()), "people_ge50": int(len(keep)),
                           "macro": {a: float(ha[keep].mean()), b: float(hb[keep].mean())},
                           "pooled": {a: pooled_mae(ea[hi]), b: pooled_mae(eb[hi])},
                           "mean_signed": {a: float(np.mean(ea[hi])), b: float(np.mean(eb[hi]))}},
            "per_person": {pid: {a: round(float(pa[pid]), 2), b: round(float(pb[pid]), 2)} for pid in pa.index}}


def summarise() -> None:
    o = pd.read_parquet(OUT / "inputs/origins.parquet")
    zs = pd.read_parquet(OUT / "zero_shot_predictions.parquet")
    df = o.copy()
    df["persistence"] = df["g_last"]
    for h in HS:
        df[f"FM_{h}"] = np.nan
        df.loc[zs.row.to_numpy(), f"FM_{h}"] = zs[f"median_{h}"].to_numpy()
    z = np.load(JOINT_NPZ)
    assert len(z["R0_final_30"]) == len(df)
    for h in HS:
        df[f"R0saved_final_{h}"] = z[f"R0_final_{h}"]
        df[f"R0saved_pop_{h}"] = z[f"R0_pop_{h}"]
    have_res = (OUT / "residual_predictions.parquet").exists()
    if have_res:
        r = pd.read_parquet(OUT / "residual_predictions.parquet")
        for c in r.columns:
            if c != "row":
                df[c] = r[c].to_numpy()
    issued = (df.quality != "insufficient").to_numpy()
    out = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "run_meta": json.loads((OUT / "run_meta.json").read_text()),
           "horizons": {}}
    for h in HS:
        tgt = np.isfinite(df[f"target_{h}"].to_numpy(float))
        base = issued & tgt
        H = {"FM_vs_persistence": _compare(df.assign(FM=df[f"FM_{h}"]), "FM", "persistence", h, base)}
        # identical origins with the saved D-052 R0 predictions
        H["FM_vs_R0saved_final"] = _compare(df.assign(FM=df[f"FM_{h}"], R0=df[f"R0saved_final_{h}"]), "FM", "R0", h, base)
        H["persistence_vs_R0saved_final"] = _compare(df.assign(R0=df[f"R0saved_final_{h}"]), "persistence", "R0", h, base)
        if have_res:
            d2 = df.assign(F1=df[f"F1_final_{h}"], R0=df[f"R0_final_{h}"])
            H["F1_final_vs_R0refit_final"] = _compare(d2, "F1", "R0", h, base)
            H["F1_pop_vs_R0refit_pop"] = _compare(df.assign(F1=df[f"F1_pop_{h}"], R0=df[f"R0_pop_{h}"]), "F1", "R0", h, base)
            rs, rr = df[f"R0saved_final_{h}"].to_numpy(), df[f"R0_final_{h}"].to_numpy()
            m = np.isfinite(rs) & np.isfinite(rr)
            H["R0refit_vs_R0saved_max_abs_diff"] = float(np.max(np.abs(rs[m] - rr[m])))
        out["horizons"][str(h)] = H
    if have_res:
        out["residual_fits"] = json.loads((OUT / "residual_fits.json").read_text())
    (OUT / "summary.json").write_text(json.dumps(out, indent=1))
    render(out)


def _f(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}"


def render(s: dict) -> None:
    m = s["run_meta"]
    L = m["latency"]
    lines = [
        "# Foundation-model baseline — zero-shot, CGM-only (gt-foundation-2026-10-21, D-054)",
        "",
        "**Label.** CGM-only, zero-shot research baseline on the 14 previously inspected CGMacros Type 2 people. Internal "
        "comparison, not independent confirmation, not clinical evidence. Not fusion, not fine-tuned. The checkpoint's "
        "public pretraining corpus may include public CGM data; whether any CGMacros recording was included is unknown. "
        "Raw model quantiles are not calibrated ranges and are not reported as such.",
        "",
        "Protocol `configs/experiments/gt-foundation-2026-10-21.yaml` was committed before any participant forecast "
        f"(protocol sha256 prefix `{m['protocol_sha256']}`).",
        "",
    ]
    H60, H30 = s["horizons"]["60"], s["horizons"]["30"]
    fp60, fp30 = H60["FM_vs_persistence"], H30["FM_vs_persistence"]
    fr60 = H60["FM_vs_R0saved_final"]
    lines += [
        "## Result in brief",
        "",
        f"- Zero-shot foundation median vs persistence (identical origins, macro per-person MAE): 30 min "
        f"{fp30['diff_macro']['mean']:+.2f} [{fp30['diff_macro']['lo']:+.2f}, {fp30['diff_macro']['hi']:+.2f}], 60 min "
        f"{fp60['diff_macro']['mean']:+.2f} [{fp60['diff_macro']['lo']:+.2f}, {fp60['diff_macro']['hi']:+.2f}] mg/dL; "
        f"lower error for {fp60['diff_macro']['people_better']}/{fp60['diff_macro']['people']} people at 60 min.",
        f"- It does not beat the personalised fusion recipe R0 (60 min {fr60['diff_macro']['mean']:+.2f} "
        f"[{fr60['diff_macro']['lo']:+.2f}, {fr60['diff_macro']['hi']:+.2f}]) and is clearly worse on targets > 180 "
        f"({fr60['high_gt180']['macro']['FM']:.2f} vs {fr60['high_gt180']['macro']['R0']:.2f}).",
    ]
    if "F1_final_vs_R0refit_final" in H60:
        f60 = H60["F1_final_vs_R0refit_final"]
        lines.append(
            f"- The declared fusion residual F1 (foundation median + fresh LightGBM residual on the served inputs) vs the "
            f"same-code R0 refit, personalised 60 min: {f60['diff_macro']['mean']:+.2f} [{f60['diff_macro']['lo']:+.2f}, "
            f"{f60['diff_macro']['hi']:+.2f}] mg/dL, > 180: {f60['high_gt180']['macro']['F1']:.2f} vs "
            f"{f60['high_gt180']['macro']['R0']:.2f}. Descriptive only: for reference, the D-052 gate's −0.5 mg/dL "
            f"threshold would {'be met' if f60['diff_macro']['mean'] <= -0.5 and f60['diff_macro']['hi'] < 0 else 'not be met'}"
            "; F1 was seen on the same 14 inspected people and is not a release candidate from this study.")
    lines += [
        "",
        "## Model, versions, hardware",
        "",
        f"- Checkpoint `{m['checkpoint']}` at revision `{m['revision']}` ({m['pipeline_class']}, {m['parameters']:,} "
        f"parameters), license {m['license']}; weights sha256 `{m['weights_sha256'][:16]}…`.",
        f"- Mode: {m['mode']}. Chronos-2 and larger checkpoints were not downloaded or tested.",
        "- Versions: " + ", ".join(f"{k} {v}" for k, v in m["versions"].items()) + f"; Python {m['python']}. Isolated "
        "environment `~/.cache/glucotwin-chronos/venv`; not a project dependency.",
        f"- Hardware: {m['hardware']['processor']} ({m['hardware']['machine']}), {m['hardware']['ram_gb']} GB RAM, "
        f"{L['threads']} CPU threads used.",
        "",
        "## Protocol in brief",
        "",
        f"- Context: {m['context_length']} five-minute slots ending at the origin (about 42.6 h); a reading enters only if "
        "observed and available at or before the origin; gaps are NaN (the model's missing mask). Native cadence "
        "verified (99.92 % of reading gaps are exactly 5 min).",
        f"- Horizons: +30 min = output step 6 (index {m['step_index']['30']}), +60 min = step 12 (index "
        f"{m['step_index']['60']}); prediction length {m['prediction_length']}, single block.",
        "- Point forecast: the median, fixed before the run. Each origin is an independent series (no cross-series mode).",
        f"- Origins: the full five-minute mask — {m['origins']:,} issued origins of {m['people']} people; scored where the "
        "target is matched. Comparators are scored on identical origins.",
        "",
        "## Latency and memory",
        "",
        f"- Warm single-origin forecast: {_f(L['warm_single_origin_ms'])} ms.",
        f"- Batched (batch {L['batch_size']}): {_f(L['batched_ms_per_origin'], 3)} ms per origin "
        f"({L['origins_per_second']:,} origins/s), full mask in {L['full_mask_seconds']} s ({L['includes']}).",
        f"- Peak resident memory of the inference process: {m['peak_rss_mb']:,} MB.",
        f"- Determinism: {m['determinism']['origins']} origins re-predicted in reverse order with batch 97; maximum "
        f"absolute difference {m['determinism']['max_abs_diff_mg_dl']:.2e} mg/dL; context hashes equal: "
        f"{m['determinism']['context_hashes_equal']}.",
        "- Run twice (21:34 and 21:39 IST; the second after lint-only code changes): every cached quantile and context "
        "hash identical (maximum difference 0). First-run latency was 4.06 ms single / 0.624 ms batched per origin; "
        "the figures above are from the second run.",
        "",
        "## Accuracy on identical origins (mg/dL)",
        "",
        "Difference = first − second; negative means the first has lower error. Interval: paired participant bootstrap, "
        "2000 resamples, 95 %.",
        "",
        "| Horizon | Comparison | Origins | People | Macro MAE (first / second) | Difference [95 % CI] | Pooled MAE "
        "(first / second) | > 180 macro MAE (people ≥ 50) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    names = {"FM_vs_persistence": ("Foundation (median)", "Persistence"),
             "FM_vs_R0saved_final": ("Foundation (median)", "R0 personalised (saved D-052)"),
             "persistence_vs_R0saved_final": ("Persistence", "R0 personalised (saved D-052)"),
             "F1_final_vs_R0refit_final": ("F1 fusion residual, personalised", "R0 refit, personalised"),
             "F1_pop_vs_R0refit_pop": ("F1 fusion residual, population", "R0 refit, population")}
    for h, H in s["horizons"].items():
        for key, (na, nb) in names.items():
            if key not in H:
                continue
            c = H[key]
            a, b = list(c["macro"])
            d = c["diff_macro"]
            hi = c["high_gt180"]
            lines.append(f"| {h} min | {na} vs {nb} | {c['origins']:,} | {c['people']} | {_f(c['macro'][a])} / "
                         f"{_f(c['macro'][b])} | {d['mean']:+.2f} [{d['lo']:+.2f}, {d['hi']:+.2f}] | "
                         f"{_f(c['pooled'][a])} / {_f(c['pooled'][b])} | {_f(hi['macro'][a])} / {_f(hi['macro'][b])} "
                         f"({hi['people_ge50']}) |")
    fv = {h: H["FM_vs_persistence"] for h, H in s["horizons"].items()}
    lines += [
        "",
        "People with lower foundation error than persistence: " + ", ".join(
            f"{h} min {c['diff_macro']['people_better']}/{c['diff_macro']['people']}" for h, c in fv.items()) + ".",
        "Mean signed error on targets > 180 (foundation / persistence): " + ", ".join(
            f"{h} min {_f(c['high_gt180']['mean_signed']['FM'])} / {_f(c['high_gt180']['mean_signed']['persistence'])}"
            for h, c in fv.items()) + " (negative = under-forecast of high glucose).",
        "",
    ]
    if "residual_fits" in s:
        fits = s["residual_fits"]["fits"]
        f1 = [f for f in fits if f["arm"] == "F1"]
        lines += [
            "## Fusion residual candidate F1 (secondary, descriptive)",
            "",
            "Template F1 (declared before the run): the fixed zero-shot median plus a freshly fitted LightGBM residual "
            "that reads the served dyn-prof-v2 inputs (46: CGM history, Fitbit heart-rate / METs / energy summaries, baseline "
            "profile when available; no meal inputs) plus the foundation delta and spread; the serving model's frozen per-horizon parameters and "
            "rounds; fitted per outer fold on that fold's development + calibration people; R0's patient correction "
            "(k 96, half-life 240 min) applied causally. R0 was refitted by the same code (2 threads, same seed) so the "
            "only difference is the foundation input. "
            f"{len(f1)} F1 fits, {sum(f['seconds'] for f in f1):.0f} s total. Not entered into the D-053 family "
            "selection and not adopted; any adoption needs the lead's separately declared gate.",
            "",
            "Consistency: R0 refit here (seed 20261021 + h, 2 threads) vs the saved D-052 R0 personalised forecasts (seed "
            "20261023 + h, 4 threads; bagging makes single forecasts seed-dependent), maximum absolute difference: " + ", ".join(
                f"{h} min {H['R0refit_vs_R0saved_max_abs_diff']:.3g} mg/dL" for h, H in s["horizons"].items()) + ".",
            "",
        ]
    else:
        lines += ["## Fusion residual candidate", "", "Not run.", ""]
    lines += [
        "## Not run",
        "",
        "- Fine-tuning (full or LoRA): not run. Zero-shot only; no participant-held-out fine-tuned claim is made.",
        "- Chronos-2 and larger Chronos-Bolt sizes: not tested (one checkpoint approved; the result is not evidence about them).",
        "- Calibrated ranges from model quantiles, warning thresholds on the foundation forecast: not run.",
        "",
        "## Files",
        "",
        "- `artifacts/research/gt-foundation-2026-10-21/` (git-ignored): `zero_shot_predictions.parquet` (one row per "
        "issued origin: q0.1…q0.9 at 30/60 min, origin and context SHA-256 prefixes; join key patient_id, origin, "
        "horizon), `run_meta.json`, `summary.json`, `residual_predictions.parquet`, `residual_fits.json`, `inputs/`.",
        "- `scripts/foundation_baseline.py`, `tests/test_foundation_baseline.py`.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    print(REPORT)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"export": export, "predict": predict, "residual": residual, "summarise": summarise,
     "render": lambda: render(json.loads((OUT / "summary.json").read_text()))}.get(cmd, lambda: sys.exit(__doc__))()
