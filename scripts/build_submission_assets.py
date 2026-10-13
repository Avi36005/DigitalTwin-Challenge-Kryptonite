"""Build charts, the architecture PDF and the presentation (PPTX + PDF) from saved artifacts.

Every number shown is read from artifacts/experiments/<id>/metrics.json at build time — nothing is typed in.
Usage:  uv run --group docs python scripts/build_submission_assets.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from glucotwin.config import load_experiment_config  # noqa: E402
from glucotwin.evaluation.report import profile_benefit_on_new_people, selection_disclosures  # noqa: E402
from glucotwin.features import FEATURE_SETS, PROFILE_FEATURES  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "artifacts/registry.json"  # the deck always describes the experiment behind the serving model
ASSETS = ROOT / "docs/assets"          # figures the README shows (committed)
FIGS = ROOT / "build/figures"          # figures only embedded in the deck (regenerated, not committed)
OUT = ROOT / "docs/submission"
UI = ROOT / "reports/ui"

# Same palette as the web app: near-black ink, one blue (serving model, online path, forecasts), neutral greys.
BLUE, INK, INK2, GRAY, LIGHT, AMBER = "#2563EB", "#0B1220", "#475569", "#94A3B8", "#E3E8EF", "#B45309"
plt.rcParams.update({
    "font.family": "Arial", "font.size": 11, "axes.edgecolor": LIGHT, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlecolor": INK, "figure.dpi": 200,
})

FAMILY = {"lightgbm": "LightGBM", "catboost": "CatBoost", "ridge": "Ridge"}


def serving_ids(m: dict) -> tuple[str, str, str, str]:
    """(serving label, personalization, family, feature set) — read from the metrics, never typed in."""
    sel = m["selection"]
    return sel["selected_label"], sel["serving_personalization"], sel["selected_family"], sel["selected_feature_set"]


def labels(m: dict) -> dict:
    sl, sp, fam, fs = serving_ids(m)
    other = "catboost" if fam == "lightgbm" else "lightgbm"
    name = FAMILY.get(fam, fam)
    prof = " + profile" if "prof" in fs else ""
    return {
        (sl, sp): f"{name}{prof}{' + patient adaptation' if sp == 'adaptive' else ''}\n(serving)",
        (sl, "off"): f"{name}{prof} (population)",
        (f"{other}:{fs}", "off"): f"{FAMILY[other]}{prof} (population)",
        (f"ridge:{fs}", "off"): "Ridge",
        ("linear_trend:cgm-only-v1", "off"): "Linear trend",
        ("persistence:cgm-only-v1", "off"): "Persistence",
    }


def load() -> dict:
    reg = json.loads(REGISTRY.read_text())
    version = reg["serving"]["dataset_replay"]
    entry = next(x for x in reg["models"] if x["model_version"] == version)
    return json.loads((ROOT / entry["evaluation_reference"]).read_text())


def serving_config() -> dict:
    reg = json.loads(REGISTRY.read_text())
    version = reg["serving"]["dataset_replay"]
    entry = next(x for x in reg["models"] if x["model_version"] == version)
    return json.loads((ROOT / entry["artifact_dir"] / "serving.json").read_text())


def fusion_facts(m: dict) -> dict:
    """Inputs of the serving feature set and, for a fusion-constrained experiment, the experiment it was derived from."""
    fs = FEATURE_SETS[serving_ids(m)[3]]
    n_prof = len(PROFILE_FEATURES) if fs.use_profile else 0
    base = load_experiment_config(m["experiment_id"]).get("derived_from")
    bp = ROOT / "artifacts/experiments" / str(base) / "metrics.json"
    return {"n_prof": n_prof, "n_dyn": len(fs.columns()) - n_prof, "base": base,
            "base_metrics": json.loads(bp.read_text()) if base and bp.exists() else None,
            "declared_on": load_experiment_config(m["experiment_id"]).get("declared_on"),
            "disclosures": selection_disclosures(m), "gate": bool(serving_config().get("profile_gate"))}


def submission() -> dict:
    """Team and link metadata (configs/submission.yaml); null values render as explicit 'to be added' text."""
    import yaml

    return yaml.safe_load((ROOT / "configs/submission.yaml").read_text())


def team_lines(sub: dict) -> tuple[str, str, str, str]:
    t, links = sub["team"], sub["links"]
    members = " · ".join(f"{n} (team leader)" if n == t["leader"] else n for n in t["members"])
    inst = t["institution"] or "College / incubator: to be confirmed by the team"
    repo = links["repository"] or "public GitHub link — added after the team publishes the repository"
    video = links["video"] or "unlisted YouTube link — added after recording and upload"
    return f"Team {t['name']} — {members}", inst, repo, video


def fig_mae(m: dict) -> Path:
    fr = pd.DataFrame(m["forecast_results"])
    fr = fr[fr["split"] == "test"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, h in zip(axes, (30, 60), strict=True):
        rows = []
        for (lab, pers), name in labels(m).items():
            r = fr[(fr["label"] == lab) & (fr["personalization"] == pers) & (fr["horizon"] == h)].iloc[0]
            rows.append((name, r["mae"], r["selected"]))
        names = [r[0] for r in rows]
        vals = [r[1] for r in rows]
        colors = [BLUE if r[2] else GRAY for r in rows]
        y = np.arange(len(rows))
        ax.barh(y, vals, color=colors, height=0.62)
        for yi, v, c in zip(y, vals, colors, strict=True):
            ax.text(v + 0.25, yi, f"{v:.2f}", va="center", fontsize=10, color=INK, fontweight="bold" if c == BLUE else None)
        ax.set_yticks(y, names)
        if h == 30:
            ax.invert_yaxis()  # shared y-axis: invert once
        ax.set_title(f"{h}-minute forecast", loc="left")
        ax.set_xlabel("MAE, mg/dL (lower is better)")
        ax.set_xlim(0, max(vals) * 1.18)
        ax.grid(axis="x", color="#EEF2F6")
        ax.set_axisbelow(True)
    fig.suptitle("Held-out test: macro mean of per-participant MAE (14 participants)", x=0.01, ha="left",
                 fontsize=12, color=INK2)
    fig.tight_layout()
    p = FIGS / "fig_mae_test.png"
    fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


def fig_paired(m: dict) -> Path:
    cmp = pd.DataFrame(m["comparisons"])
    fs = serving_ids(m)[3]
    want = [
        ("serving minus persistence", "Serving − persistence"),
        (f"lightgbm:{fs}: adaptive minus population", "Adaptation effect (LightGBM)"),
        (f"catboost:{fs}: adaptive minus population", "Adaptation effect (CatBoost)"),
        (f"lightgbm minus catboost ({fs}, population)", "LightGBM − CatBoost"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10, 2.9), sharey=True)
    for ax, h in zip(axes, (30, 60), strict=True):
        y = np.arange(len(want))
        for yi, (key, _) in zip(y, want, strict=True):
            r = cmp[(cmp["comparison"] == key) & (cmp["horizon"] == h)].iloc[0]
            lo, hi = r["ci95"]
            excl = hi < 0 or lo > 0
            c = BLUE if excl else GRAY
            ax.plot([lo, hi], [yi, yi], color=c, lw=2.2, solid_capstyle="round")
            ax.plot(r["mean_diff_mae"], yi, "o", color=c, ms=8, mec="white", mew=1.5)
            ax.text(1.15, yi, f"{r['mean_diff_mae']:+.2f}  [{lo:.2f}, {hi:.2f}]", va="center", fontsize=9, color=INK)
        ax.axvline(0, color=INK2, lw=1, ls=(0, (3, 3)))
        ax.set_yticks(y, [w[1] for w in want])
        if h == 30:
            ax.invert_yaxis()  # shared y-axis: invert once
        ax.set_title(f"{h} minutes", loc="left")
        ax.set_xlabel("Difference in MAE, mg/dL (negative = first is better)")
        ax.set_xlim(-3.6, 3.4)
        ax.set_xticks([-3, -2, -1, 0, 1])
    fig.suptitle("Paired per-participant differences with 95% participant-cluster bootstrap intervals "
                 "(blue: interval excludes 0)", x=0.01, ha="left", fontsize=11, color=INK2)
    fig.tight_layout()
    p = FIGS / "fig_paired_differences.png"
    fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


def fig_per_patient(m: dict) -> Path:
    pp = pd.DataFrame(m["per_patient_test"])
    aliases = m["aliases"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), sharey=True)
    order = None
    for ax, h in zip(axes, (30, 60), strict=True):
        sl, sp = serving_ids(m)[:2]
        s = pp[(pp["label"] == sl) & (pp["personalization"] == sp) & (pp["horizon"] == h)]
        b = pp[(pp["label"] == "persistence:cgm-only-v1") & (pp["horizon"] == h)]
        d = s.merge(b, on="patient_id", suffixes=("_s", "_p"))
        d["alias"] = d["patient_id"].map(aliases)
        if order is None:
            order = d.sort_values("alias")["alias"].tolist()
        d = d.set_index("alias").loc[order].reset_index()
        y = np.arange(len(d))
        for yi, r in zip(y, d.itertuples(), strict=True):
            ax.plot([r.mae_p, r.mae_s], [yi, yi], color=LIGHT, lw=2.5, zorder=1)
        ax.scatter(d["mae_p"], y, s=46, facecolor="white", edgecolor=INK2, lw=1.4, label="Persistence", zorder=2)
        ax.scatter(d["mae_s"], y, s=46, color=BLUE, label=f"Serving ({labels(m)[serving_ids(m)[:2]].split(chr(10))[0]})", zorder=3)
        better = int((d["mae_s"] < d["mae_p"]).sum())
        ax.set_title(f"{h} minutes — serving better for {better}/{len(d)}", loc="left")
        ax.set_yticks(y, d["alias"])
        if h == 30:
            ax.invert_yaxis()  # shared y-axis: invert once
        ax.set_xlabel("Test MAE, mg/dL")
        ax.grid(axis="x", color="#EEF2F6")
        ax.set_axisbelow(True)
    handles, leg_labels = axes[0].get_legend_handles_labels()
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.legend(handles, leg_labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    p = FIGS / "fig_per_participant.png"
    fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


LINE = 0.036


def _h(n: int) -> float:
    return 0.062 + n * LINE + 0.016


def _box(ax, x, top, w, title, lines, edge=INK):
    h = _h(len(lines))
    ax.add_patch(FancyBboxPatch((x, top - h), w, h, boxstyle="round,pad=0.006,rounding_size=0.016", fc="white",
                                ec=edge, lw=1.4))
    ax.text(x + 0.012, top - 0.022, title, fontsize=10.5, fontweight="bold", color=INK, va="top")
    for i, ln in enumerate(lines):
        ax.text(x + 0.012, top - 0.064 - i * LINE, ln, fontsize=8.6, color=INK2, va="top")
    return (x, top - h, w, h)


def _arrow(ax, x1, y1, x2, y2, text=None, tx=None, ty=None, ha="left"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.2))
    if text:
        ax.text(tx if tx is not None else (x1 + x2) / 2, ty if ty is not None else (y1 + y2) / 2, text, fontsize=8,
                color=INK if ha == "left" else INK2, va="center", ha=ha, style="italic")


def fig_architecture(fused: bool = False) -> Path:
    fig = plt.figure(figsize=(12, 6.6))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.02, 0.965, "GlucoTwin architecture", fontsize=15, fontweight="bold", color=INK, va="top")
    ax.text(0.02, 0.925, "Offline: reproducible commands on CPU.  Online: local API + browser. "
            "The same feature, adaptation and episode code runs in both.", fontsize=9.5, color=INK2, va="top")
    ax.text(0.02, 0.875, "OFFLINE", fontsize=9, color=INK, fontweight="bold")
    ax.text(0.54, 0.875, "ONLINE (local demo)", fontsize=9, color=BLUE, fontweight="bold")
    T = 0.845
    cg = _box(ax, 0.02, T, 0.2, "CGMacros 1.0.0", ["PhysioNet, CC BY-NC-SA 4.0", "SHA-256 verified", "data/raw (not in Git)"], GRAY)
    sy = _box(ax, 0.02, cg[1] - 0.03, 0.2, "Synthetic generator", ["Fictional SYN-A…E (CC0)", "gaps, late meals,", "short history"], GRAY)
    ad = _box(ax, 0.27, T, 0.22, "Adapter + canonical store", ["native Dexcom recovery from", "the interpolated 1-min table",
                                                              "5-min wearable summaries", "baseline labs (static profile)",
                                                              "observed_at / available_at", "Parquet per patient + SQLite"])
    _arrow(ax, 0.22, cg[1] + cg[3] / 2, 0.27, ad[1] + ad[3] * 0.7)
    _arrow(ax, 0.22, sy[1] + sy[3] / 2, 0.27, ad[1] + ad[3] * 0.3)
    og = _box(ax, 0.02, 0.36, 0.22, "Origin table", ["causal features (≤ 180 min)", "quality ok / degraded / insufficient",
                                                     "targets at +30 / +60 min", "new-onset event labels", "60/10/10/20 split + purge"])
    _arrow(ax, 0.33, ad[1], 0.17, og[1] + og[3], "build_features", tx=0.213, ty=0.40)
    _box(ax, 0.29, 0.46, 0.2, "Frozen experiment", ["persistence · trend · ridge", "LightGBM · CatBoost search",
                                                          "validation-only selection", "adaptation selection",
                                                          "conformal intervals", "alert threshold",
                                                          "single final-test run", "→ metrics.json, report"])
    _arrow(ax, 0.24, og[1] + og[3] / 2, 0.29, og[1] + og[3] / 2)
    rp = _box(ax, 0.54, T, 0.2, "Replay session", ["backend-owned clock", "releases available_at ≤ t",
                                                   "seek/reset → new revision", "cursors per revision"], BLUE)
    _arrow(ax, 0.49, rp[1] + rp[3] / 2, 0.54, rp[1] + rp[3] / 2, "source", tx=0.515, ty=rp[1] + rp[3] / 2 + 0.035,
           ha="center")
    tw = _box(ax, 0.54, rp[1] - 0.07, 0.2, "TwinEngine", ["build_features (same code)",
                                                         "model: profile + CGM + wearable" if fused else "population model",
                                                         "AdaptationState (same code)", "conformal interval",
                                                         "warning score − 180", "episode state machine",
                                                         "research alert rule", "immutable forecast record"], BLUE)
    _arrow(ax, 0.64, rp[1], 0.64, tw[1] + tw[3], "released events only", tx=0.648, ty=rp[1] - 0.035)
    _arrow(ax, 0.49, tw[1] + 0.06, 0.54, tw[1] + 0.06, "artifact\n+ registry", tx=0.515, ty=tw[1] + 0.13, ha="center")
    api = _box(ax, 0.79, T, 0.19, "FastAPI /api/v1", ["schema 1.0 (Pydantic)", "OpenAPI → TypeScript types",
                                                    "SQLite: forecasts, acks", "loopback, narrow CORS"], BLUE)
    _arrow(ax, 0.74, tw[1] + tw[3] * 0.75, 0.79, api[1] + 0.03)
    ui = _box(ax, 0.79, api[1] - 0.07, 0.19, "React web app", ["Landing page", "Overview · Participants",
                                                              "Replay · Model evidence", "Data quality"], BLUE)
    _arrow(ax, 0.885, api[1], 0.885, ui[1] + ui[3], "polling", tx=0.893, ty=api[1] - 0.035)
    p = ASSETS / "fig_architecture.png"
    fig.savefig(p, facecolor="white")
    plt.close(fig)
    return p


def fig_split() -> Path:
    fig, ax = plt.subplots(figsize=(11, 2.3))
    segs = [("Training 60%", 0, 0.6, "#CBD5E1", 0.36), ("Validation-selection 10%", 0.6, 0.7, "#93C5FD", 0.36),
            ("Calibration 10%", 0.7, 0.8, "#60A5FA", -0.42), ("Final test 20%", 0.8, 1.0, "#1D4ED8", 0.36)]
    for name, a, b, c, ly in segs:
        ax.barh(0, b - a, left=a, color=c, height=0.42, edgecolor="white", lw=2)
        ax.text((a + b) / 2, ly, name, ha="center", va="bottom" if ly > 0 else "top", fontsize=11, color=INK)
    for b in (0.6, 0.7, 0.8):
        ax.barh(0, 0.012, left=b - 0.012, color="#F59E0B", height=0.42)
    ax.text(0.0, -0.75, "One participant's timeline (~10 days); every participant is split the same way. Amber: purged origins whose "
            "60-min target + 15-min confirmation would cross a boundary.", fontsize=10, color=INK2, va="top")
    ax.set_xlim(0, 1)
    ax.set_ylim(-1.05, 0.75)
    ax.axis("off")
    p = FIGS / "fig_split.png"
    fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


def fig_twin_loop() -> Path:
    fig = plt.figure(figsize=(11, 2.8))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    boxes = [
        (0.01, "Baseline profile", ["labs and demographics", "available at initialisation"], GRAY),
        (0.21, "Released observations", ["native CGM readings", "5-min wearable summaries"], GRAY),
        (0.41, "Patient state", ["episode state · history", "adaptation (per horizon)"], INK),
        (0.61, "Forecast", ["30 / 60 min + prediction range", "warning score · reasons"], BLUE),
        (0.81, "Outcome observed later", ["matured residual updates", "the patient state"], INK),
    ]
    for x, title, lines, edge in boxes:
        ax.add_patch(FancyBboxPatch((x, 0.42), 0.17, 0.42, boxstyle="round,pad=0.006,rounding_size=0.03", fc="white", ec=edge, lw=1.5))
        ax.text(x + 0.012, 0.79, title, fontsize=10.2, fontweight="bold", color=INK, va="top")
        for i, ln in enumerate(lines):
            ax.text(x + 0.012, 0.65 - i * 0.1, ln, fontsize=9.2, color=INK2, va="top")
    for x in (0.18, 0.38, 0.58, 0.78):
        ax.annotate("", xy=(x + 0.03, 0.63), xytext=(x, 0.63), arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.3))
    ax.annotate("", xy=(0.495, 0.42), xytext=(0.895, 0.42), arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4,
                                                                            connectionstyle="arc3,rad=-0.35"))
    ax.text(0.695, 0.06, "only after the target reading is available — model weights are never refit", fontsize=9.5,
            color=INK, ha="center", style="italic")
    p = FIGS / "fig_twin_loop.png"
    fig.savefig(p, facecolor="white")
    plt.close(fig)
    return p


# ------------------------------------------------------------------------------------------------ slides


RESEARCH = ROOT / "artifacts/research/gt-nested-2026-10-12-v1/report.json"


def research_slide() -> dict | None:
    """One slide on the nested research experiment, from its saved report; omitted when it has not been run."""
    if not RESEARCH.exists():
        return None
    r = json.loads(RESEARCH.read_text())
    if r.get("status") != "completed" or (r.get("external") or {}).get("status") != "completed":
        return None
    t = r["tracks"]["multimodal_5min"]
    pipe = lambda name, mode: next(p for p in t["pipelines"] if p["pipeline"] == name and p["mode"] == mode)  # noqa: E731
    cmp = lambda rows, title, h: next(c for c in rows if c["comparison"] == title and c["horizon"] == h)  # noqa: E731
    sel, v2, per = pipe("selected", "final"), pipe("v2_recipe:dyn-v2", "v2_policy"), pipe("persistence:-", "off")
    hg = cmp(t["comparisons"], "High-glucose error (target > 180): selected minus current v2 recipe", 60)
    pol = {(p["pipeline"], p["policy"]): p for p in t["warnings"]["policies"] if p["horizon"] == 60}
    ws, wv = pol[("selected", "primary")], pol[("v2_recipe:dyn-v2", "v2_fixed")]
    ext = r["external"]
    e30, e60 = (cmp(ext["comparisons"], "Selected candidate minus persistence", h) for h in (30, 60))
    inv = json.loads((ROOT / "reports/dataset_inventory.json").read_text())
    imported = sum(d.get("parsed_participants") or 0 for d in inv["datasets"])
    ci = lambda c: f"{c['mean_diff']:+.2f} [{c['ci95'][0]:+.2f}, {c['ci95'][1]:+.2f}] mg/dL"  # noqa: E731
    f2 = lambda p, h: f"{p['horizons'][h]['mae']:.2f}"  # noqa: E731
    return {"kind": "bullets", "title": "New people and an independent cohort (research experiment)",
            "bullets": [
                "Models kept separate: the v2 recipe (LightGBM, dynamic streams only; the demo model when this experiment "
                "was declared), a Ridge five-minute candidate on CGM-only features, and a separate 15-minute LightGBM as "
                "the external check.",
                f"{imported} participants imported; {t['participants']} evaluated internally (five participant folds, each "
                f"person held out once) and {ext['participants']} evaluated externally (ShanghaiT2DM, China, opened once).",
                f"Held-out people, 30 / 60 min: candidate {f2(sel, '30')} / {f2(sel, '60')} vs v2 recipe refit "
                f"{f2(v2, '30')} / {f2(v2, '60')} vs persistence {f2(per, '30')} / {f2(per, '60')} mg/dL — but worse on large "
                f"highs ({ci(hg)} at 60 min when the target exceeded 180).",
                f"Warnings chosen for ≤ 2 false alarms per day: {ws['detected_onsets']}/{ws['true_onsets']} onsets at "
                f"{ws['false_alarms_per_observed_day']:.2f} false alarms per observed day (v2 recipe: "
                f"{wv['detected_onsets']}/{wv['true_onsets']} at {wv['false_alarms_per_observed_day']:.2f}).",
                f"External 15-minute LightGBM vs persistence: {ci(e30)} at 30 min (clear); {ci(e60)} at 60 min (inconclusive).",
                "Not promoted, and not eligible as the demo model: the Ridge candidate reads CGM only. CGMacros was already "
                "inspected, so its folds are internal validation; the next protocol also bounds high-glucose error, missed "
                "onsets and false warnings (declared, not run)."]}


def fusion_slide(m: dict, ff: dict, mae, c) -> dict:
    """Why the serving model reads the profile, and what that does not show. Numbers from the two experiments' metrics
    and the nested research report."""
    sl, sp, fam, fs = serving_ids(m)
    bm, base = ff["base_metrics"], ff["base"]
    bl, bp = bm["selection"]["selected_label"], bm["selection"]["serving_personalization"]
    name = FAMILY.get(fam, fam)

    def ev(mm):
        lab, pers = mm["selection"]["selected_label"], mm["selection"]["serving_personalization"]
        return next(e for e in mm["events"] if e["model"] == f"{lab} ({'adaptive' if pers == 'adaptive' else 'population'})"
                    and e["split"] == "test" and e["horizon"] == 60)
    eo, eb = ev(m), ev(bm)
    nested = profile_benefit_on_new_people()
    nci = {r["horizon"]: f"{r['mean_diff']:+.2f} [{r['ci95'][0]:+.2f}, {r['ci95'][1]:+.2f}] mg/dL" for r in nested}
    none = nested and all(r["ci95"][0] <= 0 <= r["ci95"][1] for r in nested)
    within = f"{fam}: profile minus dynamic-only (population)"
    return {"kind": "bullets", "title": "Fusion: what the profile adds, and what it does not show",
            "bullets": [
                f"The brief asks for a model that ingests static EHR-like data and dynamic wearable data. The demo model ({name}, {fs}) "
                f"reads {ff['n_prof']} baseline profile values and {ff['n_dyn']} glucose and wearable features in one model.",
                f"Same 14 people, later days (test): profile minus dynamic-only {c(within, 30)} at 30 min and {c(within, 60)} at 60 min "
                "(negative = profile better). Profile values are constant per person, so here they can act as an identity code.",
                (f"People held out entirely (nested experiment): {nci.get(30, '—')} at 30 min and {nci.get(60, '—')} at 60 min"
                 + (" — no reliable benefit for new people." if none else ".")) if nested else
                "Benefit for people held out entirely: not assessed on this machine.",
                f"Selection: the v2 rule applied only to profile + wearable models — a constraint declared on {ff['declared_on']}, after the "
                f"test segment had been inspected. Test MAE {mae(sl, sp, 30):.2f} / {mae(sl, sp, 60):.2f} mg/dL vs {mae(bl, bp, 30):.2f} / "
                f"{mae(bl, bp, 60):.2f} for the dynamic-only model ({base}): retrospective, same people.",
                f"Warnings: margin re-derived by the same F1 rule ({eo['threshold']:+.0f} vs {eb['threshold']:+.0f} mg/dL): "
                f"{eo['false_alarms_per_observed_patient_day']:.2f} vs {eb['false_alarms_per_observed_patient_day']:.2f} false alarms per observed day, "
                f"{eo['detected_onsets']}/{eo['true_onsets']} vs {eb['detected_onsets']}/{eb['true_onsets']} onsets, forecast lead median "
                f"{eo['qualified_lead_median']:.0f} vs {eb['qualified_lead_median']:.0f} min. A threshold trade-off, not evidence that the profile helps.",
                "Our claim: we selected a model that implements the required fusion; we have not established that profile features "
                "improve forecasting for unseen patients."]}


def slides(m: dict, sub: dict) -> list[dict]:
    team, inst, repo, video = team_lines(sub)
    fr = pd.DataFrame(m["forecast_results"])
    t = fr[fr["split"] == "test"]

    def mae(label, pers, h, split="test"):
        d = fr[(fr["split"] == split) & (fr["label"] == label) & (fr["personalization"] == pers) & (fr["horizon"] == h)]
        return float(d["mae"].iloc[0])

    cmp = pd.DataFrame(m["comparisons"])

    def c(key, h):
        r = cmp[(cmp["comparison"] == key) & (cmp["horizon"] == h)].iloc[0]
        return f"{r['mean_diff_mae']:+.2f} mg/dL [{r['ci95'][0]:.2f}, {r['ci95'][1]:.2f}]"

    sl, sp, sfam, sfs = serving_ids(m)
    sname = FAMILY.get(sfam, sfam)
    ev = pd.DataFrame(m["events"])
    e = ev[(ev["model"] == f"{sl} ({'adaptive' if sp == 'adaptive' else 'population'})") & (ev["split"] == "test") & (ev["horizon"] == 60)].iloc[0]
    ep = ev[(ev["model"] == "persistence") & (ev["split"] == "test") & (ev["horizon"] == 60)].iloc[0]
    corrected = "qualified_lead_median" in ev.columns and e.get("qualified_lead_median") is not None
    corrects = m.get("corrects_experiment_id")
    iv = pd.DataFrame(m["intervals"])
    ivs = iv[(iv["label"] == sl) & (iv["personalization"] == sp) & (iv["split"] == "test")]
    lo = pd.DataFrame(m["lopo"]).groupby("horizon")[["lopo_population_mae", "lopo_adaptive_mae"]].mean()
    sens = pd.DataFrame(m["sensitivity"])
    sens = sens[sens["split"] == "test"].set_index("horizon")
    seg = m["cohort"]["by_segment"]
    cand = pd.DataFrame(m["selection"]["candidates"]).sort_values("selection_score")
    serving_rows = t[t["selected"]]
    ss = serving_rows.set_index("horizon")
    pp = pd.DataFrame(m["per_patient_test"])
    n_pt = pp["patient_id"].nunique()

    def better(h):
        a = pp[(pp["label"] == "persistence:cgm-only-v1") & (pp["horizon"] == h)].set_index("patient_id")["mae"]
        b = pp[(pp["label"] == m["selection"]["selected_label"]) & (pp["personalization"] == m["selection"]["serving_personalization"])
               & (pp["horizon"] == h)].set_index("patient_id")["mae"]
        return int((b < a.reindex(b.index)).sum())
    ff = fusion_facts(m)
    disc, base, bm = ff["disclosures"], ff["base"], ff["base_metrics"]
    eligible = m["selection"].get("eligible_feature_sets") or []
    sel_table = [["Candidate", "Val. MAE 30", "Val. MAE 60", "Score"]] + [
        [r.label, f"{r.selection_mae_30:.2f}", f"{r.selection_mae_60:.2f}", f"{r.selection_score:.2f}"] for r in cand.itertuples()]
    return [
        {"kind": "title", "title": "GlucoTwin", "subtitle": "Personalized glucose forecasting between clinic visits",
         "body": ["Digital Twin Challenge 2026 · Happiest Health", team, inst,
                  "Student research prototype — not a medical device"]},
        {"kind": "bullets", "title": "The problem: what happens between appointments",
         "bullets": ["HbA1c summarises ~3 months of glucose; it cannot show short high-glucose excursions (NIDDK).",
                     "WHO identifies continuity of care and diabetes monitoring as ongoing challenges in India.",
                     "Continuous glucose monitors produce ~288 readings a day — too many to review by hand.",
                     "Question for the clinician: “Which monitored patient’s glucose pattern merits review, and what observations support that?”",
                     "Our target: forecast glucose 30 and 60 minutes ahead and warn of a NEW sustained episode > 180 mg/dL (≥ 15 min), for Type 2 diabetes."]},
        {"kind": "bullets", "title": "Use case and boundaries",
         "bullets": ["User: a clinician reviewing a small monitored cohort; secondary user: a reviewer inspecting evidence.",
                     "Workflow (proposed): baseline labs at a visit → CGM + wearable measurements → twin forecasts → review list.",
                     "Shows: observed vs predicted glucose, uncertainty, data freshness, factual reasons, research warnings.",
                     "Never: insulin or medication advice, triage, live device claims, LLM-generated predictions.",
                     "Potential fit with diagnostics + outpatient services is a proposal — no partnership or pilot is claimed."]},
        {"kind": "bullets_below", "title": "What makes it a twin (operational definition)", "image": str(FIGS / "fig_twin_loop.png"),
         "bullets": ["Versioned patient state: baseline profile, episode state, adaptation state, issued forecasts.",
                     "Incoming observations released by a replay clock (only what was available at that time).",
                     "Population forecaster + patient-specific correction learned from that person’s matured forecast errors.",
                     "Measured updates over time — a statistical research twin, not a physiological simulator."]},
        {"kind": "bullets", "title": "Data and provenance",
         "bullets": ["CGMacros 1.0.0 (PhysioNet, CC BY-NC-SA 4.0): 45 adults, ~10 days, Dexcom G6 Pro + Libre Pro (blinded), Fitbit, meals, screening labs.",
                     f"Primary cohort: {m['cohort']['participants']} participants in the dataset’s Type 2 group (HbA1c > 6.4 %); 31 others replayable but excluded.",
                     "Finding: the published 1-minute CGM columns are linearly interpolated. We recover native 5-minute Dexcom readings (integer knots) and never count interpolated rows.",
                     "Undocumented columns reported, not interpreted; documented error codes excluded; dates shifted; timezone unknown → synthetic clock, no time-of-day features.",
                     "Synthetic fictional participants exercise edge cases (gaps, late meal logs, short history) with no download."]},
        {"kind": "bullets_below", "title": "Information availability and leakage controls", "image": str(FIGS / "fig_split.png"),
         "bullets": ["Every record carries observed_at and available_at; a forecast at t uses only records with both ≤ t.",
                     "Meals excluded from the primary model (logging time unknown); tested separately as an optimistic sensitivity.",
                     ("Protocol frozen before fitting; model, adaptation, intervals and alert threshold chosen on validation; test evaluated once."
                      if not corrects else
                      f"Protocol frozen before fitting; model, adaptation, intervals and alert threshold chosen on validation. Results shown ({m['experiment_id']}) re-run {base}'s protocol with one change, declared after its test segment had been inspected: the serving model must read the baseline profile and the wearable streams."
                      if disc and base else
                      f"Protocol frozen before fitting; model, adaptation, intervals and alert threshold chosen on validation. Results shown are a corrected re-run ({m['experiment_id']}) of {corrects} after two code fixes — same protocol, same test segment, already inspected."),
                     "Adaptation uses a residual only after its target reading was available; missing future data is censored, never negative."]},
        {"kind": "image", "title": "Architecture", "image": str(ASSETS / "fig_architecture.png")},
        {"kind": "bullets", "title": "Models and personalization",
         "bullets": [*([f"Fusion: the serving model reads {ff['n_dyn']} dynamic features (CGM history, wearable heart rate and activity) and {ff['n_prof']} static baseline profile values (age, sex, BMI, HbA1c, fasting glucose and insulin, triglycerides, HDL) in one model."] if ff["n_prof"] else []),
                     "Baselines: persistence, bounded linear trend, ridge regression.",
                     "Direct per-horizon gradient-boosted trees: LightGBM (starting point) and CatBoost (challenger), equal 12-trial seeded searches, identical inputs and origins.",
                     "Patient adaptation (same policy for both families): shrunk, bounded, decaying mean of matured residuals vs the frozen population forecast; weights never refit.",
                     "Prediction ranges: split-conformal, target coverage 80 %, calibrated on the calibration segment for the exact serving pipeline.",
                     "Warning: max forecast within 60 min − 180 mg/dL — an uncalibrated score, never shown as a probability."]},
        {"kind": "table", "title": "Why this learner: validation-only selection", "table": sel_table,
         "note": (f"Declared rule: lowest mean per-participant MAE over both horizons; candidates within 0.5 mg/dL tie → simpler family, then smaller feature set. "
                  f"Eligible for serving: {', '.join(eligible)} only (profile + wearable), a constraint added on {ff['declared_on']} after the test segment had been inspected, to meet the fusion requirement. "
                  f"Selected: {m['selection']['selected_label']} with patient adaptation. Without the constraint the same rule picks {bm['selection']['selected_label']} (the earlier model, {base})."
                  if disc and bm else
                  f"Declared rule: lowest mean per-participant MAE over both horizons; candidates within 0.5 mg/dL tie → simpler family, then smaller feature set. "
                  f"Selected: {m['selection']['selected_label']} with patient adaptation (adopted on validation). "
                  f"Best validation score: {cand.iloc[0]['label']} ({cand.iloc[0]['selection_score']:.2f}). The declared tie-break chose the simpler configuration; we did not switch after seeing test results.")},
        *([fusion_slide(m, ff, mae, c)] if disc and bm else []),
        {"kind": "image", "title": "Clinician workflow: the twin workspace", "image": str(UI / "03-forecast-with-interval-recorded.png"),
         "caption": "Recorded-data replay in the held-out test period: current glucose, 30/60-minute forecasts with prediction ranges (target coverage 80 %), saved earlier forecasts, research warnings with outcomes, review status and data quality."},
        {"kind": "image", "title": "Demonstration: evidence behind a forecast", "image": str(UI / "04-forecast-evidence-dialog.png"),
         "caption": "Each forecast is immutable and inspectable: information cutoff, model version, evaluation segment, population forecast vs patient correction, factual explanations."},
        {"kind": "image", "title": "Measured evaluation: forecast accuracy (held-out test)", "image": str(FIGS / "fig_mae_test.png"),
         "caption": f"Serving − persistence: {c('serving minus persistence', 30)} at 30 min, {c('serving minus persistence', 60)} at 60 min. "
                    f"Test origins {seg['test']['origins']:,} (≈ {seg['test']['covered_hours']:.0f} h); forecasts issued for {ss.loc[30, 'coverage'] * 100:.1f} % of origins with a target."},
        {"kind": "image", "title": "Measured evaluation: does personalization help?", "image": str(FIGS / "fig_paired_differences.png"),
         "caption": f"Adaptation ({sname}): {c(f'{sl}: adaptive minus population', 30)} at 30 min, {c(f'{sl}: adaptive minus population', 60)} at 60 min — small; "
                    f"population {mae(sl, 'off', 30):.2f} / {mae(sl, 'off', 60):.2f}, frozen state {mae(sl, 'frozen_state', 30):.2f} / {mae(sl, 'frozen_state', 60):.2f}, adaptive {mae(sl, 'adaptive', 30):.2f} / {mae(sl, 'adaptive', 60):.2f} mg/dL. "
                    f"New-participant cold start: {lo.loc[30, 'lopo_population_mae']:.2f}/{lo.loc[60, 'lopo_population_mae']:.2f} → {lo.loc[30, 'lopo_adaptive_mae']:.2f}/{lo.loc[60, 'lopo_adaptive_mae']:.2f} mg/dL with adaptation."},
        {"kind": "image", "title": "Measured evaluation: every participant", "image": str(FIGS / "fig_per_participant.png"),
         "caption": "Per-participant test MAE, persistence vs the serving pipeline. Gains are uneven: large for some participants, none for a few at 60 minutes. Fourteen people cannot establish population-level performance."},
        {"kind": "bullets", "title": "Measured evaluation: early warning and uncertainty",
         "bullets": [f"60-min warning (test, margin threshold {e['threshold']:+.0f} mg/dL chosen on validation by F1): {int(e['detected_onsets'])}/{int(e['true_onsets'])} new onsets detected, precision {e['precision']:.2f}, "
                     f"{int(e['false_alarm_episodes'])} false alarms ("
                     + (f"{e['false_alarms_per_observed_patient_day']:.2f} per observed patient-day; " if corrected else "")
                     + f"{e['false_alarms_per_patient_day']:.2f} per eligible day)"
                     + (f"; forecast lead median {e['qualified_lead_median']:.0f} min (episode start {e['lead_time_median']:.0f} min)." if corrected else f", median lead {e['lead_time_median']:.0f} min."),
                     f"Same procedure on persistence (fires at glucose ≥ {180 + ep['threshold']:.0f}): {int(ep['detected_onsets'])}/{int(ep['true_onsets'])} detected, {int(ep['false_alarm_episodes'])} false alarms ("
                     + (f"{ep['false_alarms_per_observed_patient_day']:.2f} per observed patient-day; " if corrected else "")
                     + f"{ep['false_alarms_per_patient_day']:.2f} per eligible day).",
                     f"Prediction ranges (target coverage 80 %) covered {ivs[ivs['horizon'] == 30]['coverage'].iloc[0] * 100:.1f} % (30 min) and {ivs[ivs['horizon'] == 60]['coverage'].iloc[0] * 100:.1f} % (60 min) on test — under-covered; no guarantee claimed.",
                     f"Optimistic meal logging: {sens.loc[60, 'mae']:.2f} vs {sens.loc[60, 'serving_population_mae']:.2f} mg/dL at 60 min — timely meal data would likely help most."]},
        *([research_slide()] if research_slide() else []),
        {"kind": "bullets", "title": "Project outcomes",
         "bullets": ["Built: a working personalized glucose twin — replay API with a backend-owned clock, immutable forecasts, research warnings with outcomes — and a clinician workspace (landing page, Overview, Participants, Replay sessions, Model evidence, Data quality).",
                     "Found and corrected a data-provenance problem: the published 1-minute CGM values are interpolated; only native 5-minute readings are used.",
                     f"{'Measured on held-out test (retrospective)' if disc else 'Measured on held-out test (corrected re-run)' if corrects else 'Measured once on held-out test'}: {better(30)}/{n_pt} participants improved over persistence at 30 min and {better(60)}/{n_pt} at 60 min; "
                     f"MAE {ss.loc[30, 'mae']:.2f} / {ss.loc[60, 'mae']:.2f} mg/dL vs {mae('persistence:cgm-only-v1', 'off', 30):.2f} / {mae('persistence:cgm-only-v1', 'off', 60):.2f}.",
                     f"Personalization: small gains ({c(f'{sl}: adaptive minus population', 30).split(' [')[0]} and {c(f'{sl}: adaptive minus population', 60).split(' [')[0]}). "
                     f"Warnings: {int(e['detected_onsets'])}/{int(e['true_onsets'])} onsets detected with {int(e['false_alarm_episodes'])} false alarms — the F1 threshold rule ignores review workload.",
                     (f"Corrected after an independent review (activity-window defect, online warning double-credit; {corrects} preserved), then re-run with the fusion "
                      f"constraint ({m['experiment_id']}); the dynamic-only model of {base} stays registered for rollback." if disc and base else
                      "Corrected after an independent review: an activity-window feature defect and an online warning double-credit were fixed and the protocol re-run "
                      f"({m['experiment_id']}); the original {corrects} results are preserved." if corrects else
                      "Every result regenerates from saved artifacts."),
                     "Reproducible: synthetic mode needs no download; recorded-data results regenerate from versioned configs; a fresh copy passes the automated backend, frontend and browser tests."]},
        {"kind": "bullets", "title": "Limitations",
         "bullets": ["14 participants from one US site; overlapping windows are not independent patients.",
                     "No Indian participants — nothing here establishes performance for patients in India.",
                     "Blinded research CGMs replayed with assumed zero latency; native timestamps known to the minute.",
                     "Medication and insulin use unknown; meal logging time undocumented.",
                     *(["Profile fusion: profile values are constant per person, so with 14 people they can act as an identity code; no benefit was shown on people held out entirely."] if disc else []),
                     "Prediction ranges under-cover; the warning score is uncalibrated and its threshold rule (F1) ignores review workload; 180 mg/dL is a research threshold, not triage.",
                     "Retrospective replay only: no clinician workflow, outcome or safety study. Optional Chronos-Bolt not run."]},
        {"kind": "bullets", "title": "Next steps: evidence needed before use with Indian patients",
         "bullets": ["Prospective, consented Indian cohort with unblinded CGMs, recorded transmission latency, medications and meal logging times.",
                     "Re-evaluate held-out participants (cold start) and per-site calibration; report subgroup performance.",
                     "AI-READI five-minute CGM and wearable data (access not yet requested; steps listed) for a larger new-person evaluation under the declared protocol gt-nested-2026-10-12-v2.",
                     "Clinician usability study of the review workflow; regulatory and data-protection review (DPDP Act).",
                     "Optional: compare a fine-tuned time-series foundation model (e.g. Chronos-Bolt) under the same protocol."]},
        {"kind": "bullets", "title": "Team, links, reproducibility and licenses",
         "bullets": [f"{team}. {inst}.",
                     f"Code: {repo} — MIT license (code only). Quick start: make setup · make synthetic · make dev.",
                     f"Demo video (20:00): {video}. Architecture: docs/submission/GlucoTwin_Architecture.pdf.",
                     "Data: CGMacros 1.0.0, Gutierrez-Osuna, Kerr, Mortazavi, Das (2025), PhysioNet, doi:10.13026/3z8q-x658, CC BY-NC-SA 4.0; "
                     "ShanghaiT2DM, Zhao, Zhu, Wang, Rao (2022), figshare, doi:10.6084/m9.figshare.21600933.v5, CC BY 4.0.",
                     f"All results: experiment {m['experiment_id']}, artifacts/experiments/…/metrics.json; reports/evaluation_report.md."]},
    ]


def build_pptx(deck: list[dict], path: Path) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Emu, Inches, Pt

    def rgb(h):
        return RGBColor.from_string(h.lstrip("#"))

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    W = prs.slide_width

    def textbox(slide, x, y, w, h, text, size=18, bold=False, color=INK, font="Arial"):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = text
        r.font.size, r.font.bold, r.font.name = Pt(size), bold, font
        r.font.color.rgb = rgb(color)
        return tf

    for i, s in enumerate(deck, start=1):
        sl = prs.slides.add_slide(blank)
        bar = sl.shapes.add_shape(1, 0, 0, W, Inches(0.12))
        bar.fill.solid()
        bar.fill.fore_color.rgb = rgb(INK)
        bar.line.fill.background()
        if s["kind"] == "title":
            textbox(sl, Inches(0.9), Inches(2.0), Inches(11), Inches(1.2), s["title"], 54, True)
            textbox(sl, Inches(0.9), Inches(3.2), Inches(11), Inches(0.8), s["subtitle"], 26, False, BLUE)
            tf = textbox(sl, Inches(0.9), Inches(4.4), Inches(11), Inches(1.6), s["body"][0], 18, False, INK2)
            for line in s["body"][1:]:
                p = tf.add_paragraph()
                r = p.add_run()
                r.text = line
                r.font.size, r.font.name = Pt(18), "Arial"
                r.font.color.rgb = rgb(INK2)
            continue
        textbox(sl, Inches(0.6), Inches(0.35), Inches(12.1), Inches(0.8), s["title"], 30, True)
        textbox(sl, Inches(11.6), Inches(7.0), Inches(1.5), Inches(0.4), f"{i}", 11, False, INK2)
        if s["kind"] in ("bullets", "bullets_image"):
            w = Inches(12.1) if s["kind"] == "bullets" else Inches(6.3)
            tb = sl.shapes.add_textbox(Inches(0.6), Inches(1.35), w, Inches(5.6))
            tf = tb.text_frame
            tf.word_wrap = True
            for j, b in enumerate(s["bullets"]):
                p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                r = p.add_run()
                r.text = f"•  {b}"
                r.font.size, r.font.name = Pt(17 if s["kind"] == "bullets" else 15), "Arial"
                r.font.color.rgb = rgb(INK)
                p.space_after = Pt(10)
            if s["kind"] == "bullets_image":
                pic = sl.shapes.add_picture(s["image"], Inches(7.1), Inches(1.4), width=Inches(5.8))
                if pic.height > Inches(5.5):
                    ratio = Inches(5.5) / pic.height
                    pic.height, pic.width = Inches(5.5), Emu(int(pic.width * ratio))
        elif s["kind"] == "bullets_below":
            tb = sl.shapes.add_textbox(Inches(0.6), Inches(1.3), Inches(12.1), Inches(3.0))
            tf = tb.text_frame
            tf.word_wrap = True
            for j, b in enumerate(s["bullets"]):
                p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                r = p.add_run()
                r.text = f"•  {b}"
                r.font.size, r.font.name = Pt(16), "Arial"
                r.font.color.rgb = rgb(INK)
                p.space_after = Pt(8)
            pic = sl.shapes.add_picture(s["image"], Inches(0.6), Inches(4.35), width=Inches(12.1))
            if pic.height > Inches(2.95):
                ratio = Inches(2.95) / pic.height
                pic.height, pic.width = Inches(2.95), Emu(int(pic.width * ratio))
                pic.left = int((W - pic.width) / 2)
        elif s["kind"] == "image":
            pic = sl.shapes.add_picture(s["image"], Inches(0.6), Inches(1.3), width=Inches(12.1))
            maxh = Inches(5.0 if s.get("caption") else 5.9)
            if pic.height > maxh:
                ratio = maxh / pic.height
                pic.height, pic.width = maxh, Emu(int(pic.width * ratio))
                pic.left = int((W - pic.width) / 2)
            if s.get("caption"):
                textbox(sl, Inches(0.6), Inches(6.45), Inches(12.1), Inches(0.9), s["caption"], 13, False, INK2)
        elif s["kind"] == "table":
            rows, cols = len(s["table"]), len(s["table"][0])
            gt = sl.shapes.add_table(rows, cols, Inches(0.6), Inches(1.35), Inches(8.2), Inches(0.36 * rows)).table
            for r_i, row in enumerate(s["table"]):
                for c_i, val in enumerate(row):
                    cell = gt.cell(r_i, c_i)
                    cell.text = str(val)
                    para = cell.text_frame.paragraphs[0]
                    para.runs[0].font.size, para.runs[0].font.name = Pt(13), "Arial"
                    para.runs[0].font.bold = r_i == 0 or str(row[0]) == SERVING_LABEL
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = rgb("#FFFFFF")  # white cells; the selected row is bold blue text
                    para.runs[0].font.color.rgb = rgb(BLUE if str(row[0]) == SERVING_LABEL else INK)
            textbox(sl, Inches(9.1), Inches(1.35), Inches(3.8), Inches(5.5), s["note"], 14, False, INK2)
    prs.save(path)


def build_pdf(deck: list[dict], path: Path) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, Table, TableStyle

    W, H = 13.333 * 72, 7.5 * 72
    cv = canvas.Canvas(str(path), pagesize=(W, H))
    cv.setTitle("GlucoTwin — personalized glucose forecasting between clinic visits")
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=15, leading=20, textColor=HexColor(INK), spaceAfter=9)
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=12, leading=16, textColor=HexColor(INK2))

    def image(pathstr, x, y, maxw, maxh):
        img = ImageReader(pathstr)
        iw, ih = img.getSize()
        sc = min(maxw / iw, maxh / ih)
        cv.drawImage(img, x + (maxw - iw * sc) / 2, y + (maxh - ih * sc) / 2, iw * sc, ih * sc)

    for i, s in enumerate(deck, start=1):
        cv.setFillColor(HexColor(INK))
        cv.rect(0, H - 9, W, 9, stroke=0, fill=1)
        if s["kind"] == "title":
            cv.setFillColor(HexColor(INK))
            cv.setFont("Helvetica-Bold", 54)
            cv.drawString(65, H - 210, s["title"])
            cv.setFillColor(HexColor(BLUE))
            cv.setFont("Helvetica", 26)
            cv.drawString(65, H - 260, s["subtitle"])
            cv.setFillColor(HexColor(INK2))
            cv.setFont("Helvetica", 18)
            for j, line in enumerate(s["body"]):
                cv.drawString(65, H - 330 - j * 28, line)
            cv.showPage()
            continue
        cv.setFillColor(HexColor(INK))
        cv.setFont("Helvetica-Bold", 28)
        cv.drawString(43, H - 70, s["title"])
        cv.setFillColor(HexColor(INK2))
        cv.setFont("Helvetica", 10)
        cv.drawRightString(W - 40, 22, str(i))
        top = H - 100
        if s["kind"] in ("bullets", "bullets_image"):
            width = W - 86 if s["kind"] == "bullets" else 450
            y = top
            for b in s["bullets"]:
                p = Paragraph(f"•&nbsp;&nbsp;{b}", body)
                _, h = p.wrap(width, 400)
                p.drawOn(cv, 43, y - h)
                y -= h + 10
            if s["kind"] == "bullets_image":
                image(s["image"], 510, 60, W - 550, top - 70)
        elif s["kind"] == "bullets_below":
            y = top
            for b in s["bullets"]:
                p = Paragraph(f"•&nbsp;&nbsp;{b}", ParagraphStyle("bb", parent=body, fontSize=14.5, leading=19))
                _, h = p.wrap(W - 86, 400)
                p.drawOn(cv, 43, y - h)
                y -= h + 8
            image(s["image"], 43, 30, W - 86, y - 45)
        elif s["kind"] == "image":
            cap_h = 70 if s.get("caption") else 0
            image(s["image"], 43, 50 + cap_h, W - 86, top - 60 - cap_h)
            if s.get("caption"):
                p = Paragraph(s["caption"], small)
                _, h = p.wrap(W - 86, 100)
                p.drawOn(cv, 43, 40 + cap_h - h)
        elif s["kind"] == "table":
            t = Table(s["table"], colWidths=[230, 110, 110, 90])
            style = [("FONT", (0, 0), (-1, -1), "Helvetica", 12), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 12),
                     ("TEXTCOLOR", (0, 0), (-1, -1), HexColor(INK)), ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor(LIGHT)),
                     ("LINEBELOW", (0, 0), (-1, 0), 1, HexColor(INK)), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                     ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
            for r_i, row in enumerate(s["table"]):
                if row[0] == SERVING_LABEL:
                    style += [("TEXTCOLOR", (0, r_i), (-1, r_i), HexColor(BLUE)),
                              ("FONT", (0, r_i), (-1, r_i), "Helvetica-Bold", 12)]
            t.setStyle(TableStyle(style))
            _, h = t.wrap(560, 400)
            t.drawOn(cv, 43, top - h)
            p = Paragraph(s["note"], ParagraphStyle("n", parent=small, fontSize=13, leading=18))
            _, h2 = p.wrap(W - 660, 400)
            p.drawOn(cv, 630, top - h2)
        cv.showPage()
    cv.save()


def build_architecture_pdf(path: Path, m: dict) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph

    W, H = 13.333 * 72, 7.5 * 72
    cv = canvas.Canvas(str(path), pagesize=(W, H))
    cv.setTitle("GlucoTwin architecture")
    img = ImageReader(str(ASSETS / "fig_architecture.png"))
    iw, ih = img.getSize()
    sc = min((W - 60) / iw, (H - 40) / ih)
    cv.drawImage(img, (W - iw * sc) / 2, (H - ih * sc) / 2, iw * sc, ih * sc)
    cv.showPage()
    st = ParagraphStyle("b", fontName="Helvetica", fontSize=12.5, leading=17, textColor=HexColor(INK), spaceAfter=8)
    cv.setFont("Helvetica-Bold", 22)
    cv.setFillColor(HexColor(INK))
    cv.drawString(40, H - 55, "Forecast lifecycle, availability boundary and state ownership")
    ff = fusion_facts(m)
    sfs = serving_ids(m)[3]
    model_line = (
        f"<b>2. Population model.</b> {FAMILY.get(serving_ids(m)[2], serving_ids(m)[2])} predicts glucose change at +30 and +60 minutes from "
        f"{ff['n_dyn'] + ff['n_prof']} features in one model (feature set {sfs}): {ff['n_dyn']} trailing glucose and wearable features "
        "(each 5-minute wearable summary counts only the part inside the lookback window)"
        + (f" and {ff['n_prof']} static baseline profile values (age, sex, BMI, HbA1c, fasting glucose and insulin, triglycerides, "
           "HDL), assumed known at the start of the record" + ("; the model abstains when any of them is unavailable" if ff["gate"] else "")
           if ff["n_prof"] else "")
        + ". Artifacts carry a transformation fingerprint; mismatched weights are refused.")
    items = [
        "<b>1. Origin.</b> A native glucose reading becomes available at time t. Features use only records with observed_at ≤ t and available_at ≤ t (glucotwin.features.build_features — the same code offline and online).",
        model_line,
        "<b>3. Patient adaptation.</b> AdaptationState adds a shrunk, bounded, decaying correction learned only from earlier forecasts whose target readings were already available. Model weights are never refit.",
        "<b>4. Uncertainty and warning.</b> Split-conformal prediction ranges (target coverage 80 %) calibrated for this exact pipeline; warning score = max forecast within 60 min − 180 mg/dL (uncalibrated, not a probability). Warning outcomes use one shared one-to-one onset matcher offline and in replay.",
        "<b>5. Immutable record.</b> Forecasts are stored once under uuid5(session, revision, origin, model version); outcomes are revealed only when the replay clock passes their availability.",
        "<b>6. Revisions.</b> Seek/reset rebuild the twin from released events only; old cursors return 409; the browser keys caches by (session, revision, clock).",
        "<b>State ownership.</b> Canonical store (Parquet + SQLite, local) · replay clock and sessions (API memory) · twin state (per session revision, rebuilt deterministically) · issued forecasts and acknowledgements (SQLite audit) · model artifacts (checksummed registry) · UI preferences (browser).",
        "<b>Posture.</b> CPU only; loopback binding; narrow CORS; no cloud, API keys or LLMs; trusted artifacts verified by SHA-256; no pickles. Research demonstration, not production or a medical device.",
    ]
    y = H - 90
    for it in items:
        p = Paragraph(it, st)
        _, h = p.wrap(W - 80, 200)
        p.drawOn(cv, 40, y - h)
        y -= h + 8
    cv.showPage()
    cv.save()


SERVING_LABEL = ""  # set in main(): table rows of the serving model are highlighted


def main() -> None:
    global SERVING_LABEL
    ASSETS.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    m = load()
    SERVING_LABEL = serving_ids(m)[0]
    for f in (fig_mae, fig_paired, fig_per_patient):
        print(f(m))
    print(fig_architecture(fusion_facts(m)["n_prof"] > 0))
    print(fig_split())
    print(fig_twin_loop())
    build_architecture_pdf(OUT / "GlucoTwin_Architecture.pdf", m)
    deck = slides(m, submission())
    build_pptx(deck, OUT / "GlucoTwin_Presentation.pptx")
    build_pdf(deck, OUT / "GlucoTwin_Presentation.pdf")
    print(f"slides: {len(deck)} -> {OUT}")


if __name__ == "__main__":
    main()
