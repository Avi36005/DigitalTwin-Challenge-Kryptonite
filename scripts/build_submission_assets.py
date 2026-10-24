"""Build charts, the architecture PDF, the presentation (PPTX + PDF) and the team folder index from saved artifacts.

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
from architecture_diagram import build_spec, check_fit, draw_png, draw_pptx  # noqa: E402
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
BLUE, INK, INK2, GRAY, LIGHT, AMBER = "#2563EB", "#0B1220", "#1F2937", "#94A3B8", "#E3E8EF", "#B45309"
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


PROTOCOL_NOTE = ("Scores depend on the dataset, prediction task and evaluation protocol; performance on simulated "
                 "patients does not establish performance on real patients.")


def brand(sub: dict) -> str:
    """'Team Kryptonite, VESIT' — the short name used on the title slide, the README heading and the video title card."""
    t = sub["team"]
    return f"Team {t['name']}, {t['institution_short']}" if t.get("institution_short") else f"Team {t['name']}"


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
    fig.suptitle("Final test, later days of the same 14 participants: macro mean of per-participant MAE", x=0.01, ha="left",
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


ARCH_SUBTITLE = ("Two data streams fused in one model; the offline build and the online twin share the same feature and "
                 "adaptation code.")


def arch_spec(m: dict):
    ff = fusion_facts(m)
    spec = build_spec(ff["n_prof"], ff["n_dyn"])
    check_fit(spec)
    return spec


def fig_architecture(m: dict) -> Path:
    """README / architecture-PDF figure (with its own title) and a title-less copy for the PDF deck."""
    spec = arch_spec(m)
    draw_png(FIGS / "fig_architecture_slide.png", spec)
    return draw_png(ASSETS / "fig_architecture.png", spec, "GlucoTwin — system architecture", ARCH_SUBTITLE)


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

# Section labels printed above slide titles, so a reader never mixes the three kinds of evidence.
SEC_SERVING = "SERVING MODEL · later recordings of the same 14 participants it was trained on — not new people"
SEC_HELDOUT = "RESEARCH · each participant held out entirely · internal validation · not the serving model"
SEC_EXTERNAL = "RESEARCH · external cohort, CGM only · not the serving fusion model"

# Studies declared in the 21–22 Oct sprint. Their numbers are inserted only from the locked, verified summary
# (phase 2); until then every slide and table cell says "pending" — never a number.
PENDING_STUDIES = [
    {"decision": "D-053", "experiment": "gt-constrained-2026-10-21",
     "what": "Constrained LightGBM fusion: peak-aware selection with the patient correction, each person held out once, "
             "against a freshly refitted serving recipe"},
]
PENDING = "pending"
FOUNDATION = ROOT / "artifacts/research/gt-foundation-2026-10-21/summary.json"


CONSTRAINED = ROOT / "artifacts/research/gt-constrained-2026-10-21/summary.json"


def demo_notice30() -> str | None:
    """Share of ALL onsets the demo warning gave at least 30 min notice, read from reports/warning_utility.md (made from
    saved forecasts by scripts/warning_utility.py); None if that report or its demo row is missing."""
    p = ROOT / "reports" / "warning_utility.md"
    if not p.exists():
        return None
    rows = [r for r in p.read_text().splitlines() if r.startswith("| Warning |") or r.startswith("| Demo model")]
    if len(rows) != 2:
        return None
    head, demo = ([c.strip() for c in r.strip("|").split("|")] for r in rows)
    return demo[head.index("≥ 30 min")] if "≥ 30 min" in head else None


def constrained_facts() -> dict | None:
    """D-053, read from its locked summary.json; None until it exists."""
    if not CONSTRAINED.exists():
        return None
    return json.loads(CONSTRAINED.read_text())


def pending_slide() -> dict:
    d = constrained_facts()
    if d:
        P, pg, w, rg = d["procedures"], d["primary_gate"], d["warnings"], d["ranges"]["S"]
        p60, p30 = d["paired"]["S|R0|final|60"], d["paired"]["S|R0|final|30"]
        ci = lambda x: f"{x['mean_diff']:+.2f} [{x['ci95'][0]:+.2f}, {x['ci95'][1]:+.2f}]"  # noqa: E731
        hv = pg["values"]["high_worsening_60"]
        verdict = "passed" if pg["passed"] else "not met"
        return {"kind": "bullets", "section": SEC_HELDOUT,
                "title": "Research: peak-aware selection (D-053), a near miss",
                "bullets": [
                    "Declared before any formal fit; inside each held-out fold, model settings, a training weight on future "
                    "readings above 180 and the patient correction were chosen on development people only, with a guard on "
                    f"high-reading error. {d['fit_totals']['fits']:,} fresh fits, {d['fit_totals']['failures']} failures.",
                    f"60 min, against the serving recipe refitted in the same folds: {P['S']['60']['mae']:.2f} vs "
                    f"{P['R0']['60']['mae']:.2f} mg/dL, {ci(p60)}, lower for {p60['improved']} of {p60['n_participants']} people; "
                    f"30 min {ci(p30)}.",
                    f"Primary gate {verdict}: error on readings above 180 changed by {hv:+.2f} mg/dL against a declared limit of +1.0.",
                    f"Warning guardrails {'passed' if d['operational_gate']['passed'] else 'not met'}: {w['S']['fa_day']:.2f} vs "
                    f"{w['R0-P']['fa_day']:.2f} false alarms per observed day; {100 * w['S']['share30']:.1f} % vs "
                    f"{100 * w['R0-P']['share30']:.1f} % of onsets warned ≥ 30 min ahead. Exact-predictor 80 % ranges covered "
                    f"{100 * rg['30']['coverage']:.1f} % / {100 * rg['60']['coverage']:.1f} % (range guardrails "
                    f"{'passed' if d['range_gate']['passed'] else 'not met'}).",
                    ("Not adopted: one declared gate failed, so the serving model is unchanged." if not d["all_gates_passed"]
                     else "All declared gates passed; adoption still requires serving parity and integration checks."),
                    "Previously inspected people: internal validation. Absolute errors are not comparable with D-052's; only the "
                    "matched comparison is."]}
    """D-053; result text stays 'pending' until phase 2 maps its locked, verified summary."""
    bullets = []
    for st in PENDING_STUDIES:
        bullets.append(f"{st['decision']} · {st['experiment']} — {st['what']}. Result and release-gate outcome: {PENDING} "
                       "(inserted only from the locked, verified summary).")
    bullets += ["The protocol was declared before its own run. It reuses previously inspected participants, so its result "
                "is internal validation.",
                "Nothing from it reaches the app unless every declared release gate passes and the candidate passes serving "
                "parity and integration checks; otherwise the serving model is unchanged."]
    return {"kind": "bullets", "section": SEC_HELDOUT, "title": "Research, 21–22 October: constrained LightGBM (D-053)",
            "bullets": bullets}


def foundation_facts() -> dict | None:
    """D-054 zero-shot foundation baseline, read from its saved summary.json; None until it exists."""
    if not FOUNDATION.exists():
        return None
    d = json.loads(FOUNDATION.read_text())
    h = d["horizons"]
    rm = d["run_meta"]
    ci = lambda x: f"{x['mean']:+.2f} [{x['lo']:+.2f}, {x['hi']:+.2f}]"  # noqa: E731
    return {"rm": rm, "h": h, "ci": ci,
            "fm": {k: h[k]["FM_vs_persistence"]["macro"]["FM"] for k in ("30", "60")},
            "per": {k: h[k]["FM_vs_persistence"]["macro"]["persistence"] for k in ("30", "60")}}


def foundation_slide() -> dict | None:
    f = foundation_facts()
    if not f:
        return None
    h, ci, rm = f["h"], f["ci"], f["rm"]
    vp, vr = h["60"]["FM_vs_persistence"], h["60"]["FM_vs_R0saved_final"]
    return {"kind": "bullets", "section": "RESEARCH · 14 previously inspected people · internal comparison · CGM only · not served",
            "title": "Research: a zero-shot foundation-model baseline (D-054)",
            "bullets": [
                f"{rm['checkpoint']} ({rm['parameters'] / 1e6:.1f} M parameters, {rm['license']}), zero-shot on CGM only. "
                "Not fine-tuned, not a fusion model, not served.",
                f"Vs carrying the last reading forward: {ci(h['30']['FM_vs_persistence']['diff_macro'])} mg/dL at 30 min, "
                f"{ci(vp['diff_macro'])} at 60 min — lower for {vp['diff_macro']['people_better']} of "
                f"{vp['diff_macro']['people']} people.",
                f"Vs our serving recipe refitted per held-out person: {ci(vr['diff_macro'])} mg/dL at 60 min "
                f"({vr['macro']['FM']:.2f} vs {vr['macro']['R0']:.2f}) — not better; worse above 180 mg/dL.",
                "Same 14 previously inspected people: an internal comparison. Its pretraining data may include public CGM "
                "recordings."]}


def results_overview(m: dict) -> dict:
    """One labelled table, three kinds of evidence kept apart; the slide used in the video's results cutaway."""
    fr = pd.DataFrame(m["forecast_results"])
    t = fr[fr["split"] == "test"]
    sl, sp = serving_ids(m)[:2]
    pick = lambda lab, pers, h: float(t[(t["label"] == lab) & (t["personalization"] == pers) & (t["horizon"] == h)]["mae"].iloc[0])  # noqa: E731
    rows = [["Evaluated on", "Model or procedure", "MAE 30 / 60 min", "Persistence 30 / 60"],
            ["§Serving model — later recordings of the same 14 CGMacros Type 2 people (a test over time, retrospective)"],
            ["Final 20 % of each recording", "Fusion LightGBM + bounded patient correction (serving)",
             f"{pick(sl, sp, 30):.2f} / {pick(sl, sp, 60):.2f}",
             f"{pick('persistence:cgm-only-v1', 'off', 30):.2f} / {pick('persistence:cgm-only-v1', 'off', 60):.2f}"],
            ["§Participant-held-out research — 14 CGMacros people, each held out once (internal validation)"]]
    if RESEARCH.exists():
        r = json.loads(RESEARCH.read_text())
        tr = r["tracks"]["multimodal_5min"]
        pipe = lambda name, mode: next(p for p in tr["pipelines"] if p["pipeline"] == name and p["mode"] == mode)  # noqa: E731
        sel, per = pipe("selected", "final"), pipe("persistence:-", "off")
        f2 = lambda p: f"{p['horizons']['30']['mae']:.2f} / {p['horizons']['60']['mae']:.2f}"  # noqa: E731
        rows.append(["Five participant folds (D-032)", "CGM-only procedure (Ridge in 4 of 5 folds), not served",
                     f2(sel), f2(per)])
    for st in PENDING_STUDIES:
        c = constrained_facts()
        if c:
            pr = c["procedures"]
            rows.append([f"Same folds ({st['decision']})", "Peak-aware constrained fusion selection, not adopted",
                         f"{pr['S']['30']['mae']:.2f} / {pr['S']['60']['mae']:.2f}",
                         f"{pr['persistence']['30']['mae']:.2f} / {pr['persistence']['60']['mae']:.2f}"])
        else:
            rows.append([f"14 CGMacros people ({st['decision']})", st["what"].split(":")[0], PENDING, PENDING])
    f = foundation_facts()
    if f:
        rows.append(["Same 14 people (D-054)", "Zero-shot foundation model, CGM only, not served",
                     f"{f['fm']['30']:.2f} / {f['fm']['60']:.2f}", f"{f['per']['30']:.2f} / {f['per']['60']:.2f}"])
    rows.append(["§External check — ShanghaiT2DM, 98 people, CGM only; D-045 was the cohort's second opening"])
    if TWO_HOUR_EXT.exists():
        e = json.loads(TWO_HOUR_EXT.read_text())
        rows.append([f"{e['participants']} people, 15-min CGM (D-045)",
                     "Separate 15-min LightGBM, CGM only, not served",
                     f"{e['mae']['30']:.2f} / {e['mae']['60']:.2f}",
                     f"{e['persistence_mae']['30']:.2f} / {e['persistence_mae']['60']:.2f}"])
    iv = pd.DataFrame(m["intervals"])
    ivs = iv[(iv["label"] == sl) & (iv["personalization"] == sp) & (iv["split"] == "test")].set_index("horizon")
    note = ("Mean absolute error in mg/dL (lower is better), averaged over participants. Each group is a different model "
            "and test — do not compare across groups. "
            f"Serving ranges (target 80 %) covered {ivs.loc[30, 'coverage'] * 100:.1f} % / {ivs.loc[60, 'coverage'] * 100:.1f} %.")
    return {"kind": "results", "title": "Results at a glance: three kinds of evidence, kept apart", "table": rows,
            "note": note}


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
    return {"kind": "bullets", "section": SEC_HELDOUT, "title": "Research: people held out entirely",
            "bullets": [
                "Models kept separate: the v2 recipe (LightGBM, dynamic streams only; the demo model when this experiment "
                "was declared) and a Ridge five-minute candidate on CGM-only features. Neither is the serving model.",
                f"{imported} participants imported; {t['participants']} evaluated here (five participant folds, each "
                f"person held out once, protocol frozen before fitting, D-032).",
                f"Held-out people, 30 / 60 min: candidate {f2(sel, '30')} / {f2(sel, '60')} vs v2 recipe refit "
                f"{f2(v2, '30')} / {f2(v2, '60')} vs persistence {f2(per, '30')} / {f2(per, '60')} mg/dL — but worse on large "
                f"highs ({ci(hg)} at 60 min when the target exceeded 180).",
                f"Warnings chosen for ≤ 2 false alarms per day: {ws['detected_onsets']}/{ws['true_onsets']} onsets at "
                f"{ws['false_alarms_per_observed_day']:.2f} false alarms per observed day (v2 recipe: "
                f"{wv['detected_onsets']}/{wv['true_onsets']} at {wv['false_alarms_per_observed_day']:.2f}).",
                "Not promoted, and not eligible as the demo model: the Ridge candidate reads CGM only. CGMacros was already "
                "inspected, so its folds are internal validation; the next protocol also bounds high-glucose error, missed "
                "onsets and false warnings (declared, not run)."]}


def external_slide() -> dict | None:
    """External CGM-only cohort (D-032 at 30/60 min; D-045 at 120 min), on its own slide; omitted until run."""
    if not RESEARCH.exists():
        return None
    r = json.loads(RESEARCH.read_text())
    ext = r.get("external") or {}
    if ext.get("status") != "completed":
        return None
    cmp = lambda rows, title, h: next(c for c in rows if c["comparison"] == title and c["horizon"] == h)  # noqa: E731
    e30, e60 = (cmp(ext["comparisons"], "Selected candidate minus persistence", h) for h in (30, 60))
    ci = lambda c: f"{c['mean_diff']:+.2f} [{c['ci95'][0]:+.2f}, {c['ci95'][1]:+.2f}] mg/dL"  # noqa: E731
    bullets = [
        f"Who: {ext['participants']} adults with Type 2 diabetes in ShanghaiT2DM (China, FreeStyle Libre H, 15-minute "
        "readings), never trained on. No wearable or dated labs, so this checks the forecasting core only, not the fusion.",
        "What: a separate 15-minute LightGBM on CGM-only features, developed on CGMacros. It is not the serving fusion "
        "model and not the Ridge candidate.",
        f"30 / 60 minutes (D-032, the cohort's first opening): {ci(e30)} at 30 min (clear) and {ci(e60)} at 60 min "
        "(inconclusive), versus carrying the last reading forward."]
    if ext_bullet():
        bullets.append(ext_bullet())
    bullets.append("Nothing was chosen on this cohort; other frozen pipelines were reported but not adopted, because "
                   "choosing on it would turn it into a tuning set.")
    return {"kind": "bullets", "section": SEC_EXTERNAL, "title": "External check: an independent Type 2 cohort",
            "bullets": bullets}


TWO_HOUR = ROOT / "artifacts/research/gt-2h-2026-10-20/two_hour_summary.json"


def two_hour_slide() -> dict | None:
    """The two-hour research experiment (D-043), from scripts/summarise_two_hour.py's saved summary; omitted until run."""
    if not TWO_HOUR.exists():
        return None
    s = json.loads(TWO_HOUR.read_text())
    f, comps = s["forecasts"], s["comparisons"]
    mae = lambda key, h: f[key]["horizons"][str(h)]["mae"]  # noqa: E731
    cmp = lambda title, h: next(c for c in comps if c["comparison"] == title and c["horizon"] == h)  # noqa: E731
    ci = lambda c: f"{c['mean_difference']:+.2f} [{c['ci95'][0]:+.2f}, {c['ci95'][1]:+.2f}] mg/dL"  # noqa: E731
    w = {(x["pipeline"], x["horizon"]): x for x in s["warnings"]}

    def warn(h):
        x = w.get(("selected", h))
        if not x or x.get("status") != "ok":
            return f"{h}-min warning: no threshold met the 2-false-alarm budget."
        return (f"{h}-min warning: {x['detected_onsets']}/{x['true_onsets']} onsets warned, "
                f"{x['false_alarms_per_observed_day']:.2f} false alarms per observed day, median forecast lead "
                f"{x['qualified_lead_median']:.0f} min")
    prof = cmp("Profile (EHR-like) inputs: LightGBM dyn-prof-v2 minus dyn-v2", 120)
    sel = cmp("Selected (personalised) minus persistence", 120)
    return {"kind": "bullets", "section": SEC_HELDOUT, "title": "Research: warning two hours ahead",
            "bullets": [
                "The brief's example is a spike predicted 2 hours ahead. Declared before any fit (decision D-043): the "
                f"people-held-out procedure above, same folds, plus a 120-minute horizon. {s['participants']} "
                "people, each held out once; not the demo model, nothing promoted.",
                f"Forecast error at 120 min: {mae('selected|final', 120):.1f} mg/dL vs persistence "
                f"{mae('persistence:-|off', 120):.1f} ({ci(sel)}); at 60 min {mae('selected|final', 60):.1f} vs "
                f"{mae('persistence:-|off', 60):.1f}.",
                warn(120) + ". For comparison, " + warn(60) + ".",
                f"Profile (EHR-like) inputs at 120 min, LightGBM with minus without: {ci(prof)} "
                f"({'no reliable benefit' if prof['ci95'][0] <= 0 <= prof['ci95'][1] else 'better' if prof['ci95'][1] < 0 else 'worse'}"
                " on people held out).",
                "Thresholds chosen on development folds only (≤ 2 false alarms per observed day); each test fold opened once. "
                "The 14 people were inspected in earlier experiments, so this is internal validation."]}


WARN_RANGE = ROOT / "artifacts/research/gt-warn-range-2026-10-20/summary.json"


def reanalysis_slide() -> dict | None:
    """What the D-046 re-analysis fixed and what it did not, from scripts/warning_range_experiment.py's saved summary."""
    if not WARN_RANGE.exists():
        return None
    s = json.loads(WARN_RANGE.read_text())
    r, w, d = s["ranges"], s["warnings"], s["warning_diff_selected_minus_incumbent"]
    p = s["profile_prior"]["all"]["120"]["c1_minus_population"]
    p24 = s["profile_prior"]["first_24h"]["120"]["c1_minus_population"]
    cov = lambda b, h: 100 * r[b][str(h)]["coverage_pooled"]  # noqa: E731
    ci = lambda x: f"{x['mean_diff']:+.2f} [{x['ci95'][0]:+.2f}, {x['ci95'][1]:+.2f}]"  # noqa: E731
    return {"kind": "bullets", "section": SEC_HELDOUT, "title": "Research: what we fixed, and what we could not",
            "bullets": [
                "We declared each study before its own run. Later studies reused previously inspected participants, so those "
                "results are internal validation.",
                f"Fixed — prediction ranges: calibrating on all development people instead of 2 per fold raised two-hour coverage "
                f"from {cov('B0_calibration', 120):.1f} % to {cov('B1_pooled', 120):.1f} % (target 80 %; 60 min "
                f"{cov('B0_calibration', 60):.1f} → {cov('B1_pooled', 60):.1f} %), ranges "
                f"{r['B1_pooled']['120']['width_mean'] - r['B0_calibration']['120']['width_mean']:.0f} mg/dL wider.",
                f"Not shown — earlier warning: {w['selected']['early']} vs {w['incumbent']['early']} of {w['incumbent']['onsets']} "
                f"onsets warned ≥ 30 min ahead ({100 * d['early_share_diff']:+.1f} points [{100 * d['early_share_ci95'][0]:+.1f}, "
                f"{100 * d['early_share_ci95'][1]:+.1f}]) at the same workload; median lead still "
                f"{w['selected']['lead_median']:.0f} min.",
                f"Not shown — health record as a new person's starting correction: {ci(p)} mg/dL at 120 min, {ci(p24)} in the "
                "first 24 hours; the intervals cross zero, so no benefit is claimed.",
                *([blend_bullet()] if blend_bullet() else []),
                *([retrain_bullet()] if retrain_bullet() else []),
                *([joint_bullet()] if joint_bullet() else []),
                "The demo model's ranges are already pooled over all 14 people; its under-coverage most likely comes from drift between "
                "time segments, so this fix is not applied to it."]}


BLEND = ROOT / "artifacts/research/gt-blend-2026-10-21/development.json"
RETRAIN = ROOT / "artifacts/research/gt-retrain-2026-10-21/development.json"
TUNE = ROOT / "artifacts/research/gt-tune-2026-10-21/summary.json"


def tune_bullet() -> str | None:
    """D-051: nested tuning, history vs current features with equal budget."""
    if not TUNE.exists():
        return None
    d = json.loads(TUNE.read_text())
    p = d["paired"]["C1_with_history|C0_current_features|final|60"]
    r = d["paired"]["C1_with_history|R0_untuned_serving_recipe|final|60"]
    return (f"Small internal gain, below our bar — tuned retraining with 24-hour history (D-051, 1,830 fits, each person held "
            f"out): {p['mean_diff']:+.2f} [{p['ci95'][0]:+.2f}, {p['ci95'][1]:+.2f}] mg/dL at 60 min vs the equally tuned current "
            f"features, {p['improved']} of {p['n']} better; vs the refitted serving recipe {r['mean_diff']:+.2f} "
            f"[{r['ci95'][0]:+.2f}, {r['ci95'][1]:+.2f}]. Declared bar −0.5; not adopted.")


JOINT = ROOT / "artifacts/research/gt-joint-2026-10-21/summary.json"


def joint_bullet() -> str | None:
    """D-052: joint model + correction selection inside each fold, against the refitted serving recipe."""
    if not JOINT.exists():
        return None
    d = json.loads(JOINT.read_text())
    g = d["gate"]
    rg = d.get("release_guardrails", {})
    return (f"Not adopted — joint selection (D-052, 1,570 fresh fits): {g['mean_diff_60']:+.2f} [{g['ci95_60'][0]:+.2f}, "
            f"{g['ci95_60'][1]:+.2f}] mg/dL at 60 min vs the refitted serving recipe, but {g['high_worsening_60']:+.2f} on peaks "
            f"above 180 and {rg.get('fa_per_day_delta', 0):+.2f} false alarms/day — gates not met.")


def retrain_bullet() -> str | None:
    """D-049: four freshly fitted arms of the fusion recipe, development decision only."""
    if not RETRAIN.exists():
        return None
    g = {a: v["checks"]["gain_60"] for a, v in json.loads(RETRAIN.read_text())["selection"]["by_arm"].items()}
    t = json.loads(TUNE.read_text())["paired"]["C1_with_history|C0_current_features|final|60"] if TUNE.exists() else None
    return ("Not adopted — fixed and tuned retraining (D-049, D-051): best 60-min gain "
            f"{g['B1_balanced_long_history']:+.2f} mg/dL (fixed)"
            + (f", {t['mean_diff']:+.2f} [{t['ci95'][0]:+.2f}, {t['ci95'][1]:+.2f}] with tuning" if t else "")
            + ", below the declared 0.5 bar.")


def blend_bullet() -> str | None:
    """D-048: LightGBM–CatBoost blend, development decision only (the outer folds were not opened)."""
    if not BLEND.exists():
        return None
    d = json.loads(BLEND.read_text())["decision"]
    c = d["checks"]
    return (f"Not adopted — a LightGBM–CatBoost blend (D-048): {c['improvement_60']:+.2f} mg/dL at 60 min on development "
            "people against a 0.5 target; held-out folds never opened.")


TWO_HOUR_EXT = ROOT / "artifacts/research/gt-2h-ext-2026-10-20/two_hour_external_summary.json"


def ext_bullet() -> str | None:
    """Independent-cohort two-hour check (D-045), from scripts/summarise_two_hour_external.py's saved summary."""
    if not TWO_HOUR_EXT.exists():
        return None
    e = json.loads(TWO_HOUR_EXT.read_text())
    c = e["minus_persistence"]["120"]
    return (f"Two hours ahead (D-045, declared before any fit; its first 120-minute assessment and the cohort's second opening): "
            f"{e['mae']['120']:.1f} vs persistence {e['persistence_mae']['120']:.1f} mg/dL at 120 min "
            f"({c['mean_diff']:+.2f} [{c['ci95'][0]:+.2f}, {c['ci95'][1]:+.2f}]), better for {c['improved']} of {c['n']} people.")


def guardrails_slide() -> dict:
    """Safety guardrails enforced in code (same list as the README's Safety guardrails table)."""
    return {"kind": "bullets", "title": "Safety guardrails built into the twin",
            "bullets": [
                "Abstains instead of guessing: no forecast with under 60 min of history or no new reading; marked Stale after "
                "15 min; weak inputs flagged Degraded, with the reason.",
                "No input is used before it was available; the fusion model abstains when a health-record value is missing.",
                "Patient correction: only from observed outcomes, needs 6, capped at ±25 mg/dL, reset after a 3-hour gap.",
                "Warnings stay Outcome pending until they can be judged, then match an onset or count as a false alarm.",
                "80 % prediction ranges shown with measured coverage; not a medical device, no treatment advice.",
                "Opened tests are locked; the app reproduced all 15,440 saved test forecasts within 0.05 mg/dL."]}


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
    ev = pd.DataFrame(m["events"])
    e = ev[(ev["model"] == f"{sl} ({'adaptive' if sp == 'adaptive' else 'population'})") & (ev["split"] == "test") & (ev["horizon"] == 60)].iloc[0]
    corrected = "qualified_lead_median" in ev.columns and e.get("qualified_lead_median") is not None
    corrects = m.get("corrects_experiment_id")
    iv = pd.DataFrame(m["intervals"])
    ivs = iv[(iv["label"] == sl) & (iv["personalization"] == sp) & (iv["split"] == "test")]
    sens = pd.DataFrame(m["sensitivity"])
    sens = sens[sens["split"] == "test"].set_index("horizon")
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
         "body": [brand(sub), team.split(" — ", 1)[-1], inst, "Digital Twin Challenge 2026 · Happiest Health",
                  "Student research prototype — not a medical device"]},
        {"kind": "bullets", "title": "The problem: what happens between appointments",
         "bullets": ["HbA1c summarises ~3 months of glucose; it cannot show short high-glucose excursions (NIDDK).",
                     "WHO identifies continuity of care and diabetes monitoring as ongoing challenges in India.",
                     "Continuous glucose monitors produce ~288 readings a day — too many to review by hand.",
                     "Question for the clinician: “Which monitored patient’s glucose pattern merits review, and what observations support that?”",
                     "Our target: forecast glucose 30 and 60 minutes ahead and warn of a NEW sustained episode > 180 mg/dL (≥ 15 min), for Type 2 diabetes."]},
        {"kind": "bullets", "title": "Use case and boundaries",
         "bullets": ["Hypothetical example (an illustration, not a deployment): a diabetes educator in Mumbai follows adults with Type 2 diabetes who wear CGMs between quarterly visits, and opens one person’s replay to see forecasts, warnings and the data behind them.",
                     "User: a clinician reviewing a small monitored cohort; secondary user: a reviewer inspecting evidence.",
                     "Workflow (proposed): baseline labs at a visit → CGM + wearable measurements → twin forecasts → a review queue lists replays with unreviewed warnings first (an order of work, not triage) → each person reviewed in their own workspace.",
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
         "bullets": ["A forecast at time t uses only records observed and available by t.",
                     "Meals left out of the main model (logging time unknown); tested separately.",
                     ("Protocol frozen before fitting; every choice made on validation; test evaluated once."
                      if not corrects else
                      f"Protocol frozen before fitting; choices made on validation. The fusion re-run ({m['experiment_id']}) was declared after {base}'s test had been inspected."
                      if disc and base else
                      f"Protocol frozen before fitting; choices made on validation. Results are a corrected re-run ({m['experiment_id']}) of {corrects}."),
                     "The patient correction learns only from forecasts whose outcome was already observed."]},
        {"kind": "architecture", "title": "System architecture: two data streams, one twin", "spec": arch_spec(m),
         "image": str(FIGS / "fig_architecture_slide.png")},
        {"kind": "bullets", "title": "Models and personalization",
         "bullets": [*([f"Fusion: {ff['n_dyn']} dynamic features (CGM, heart rate, activity) + {ff['n_prof']} baseline profile values (age, sex, BMI, HbA1c, labs) in one model."] if ff["n_prof"] else []),
                     "Baselines: persistence, linear trend, ridge. Learners: LightGBM and CatBoost, same search budget.",
                     "Patient correction: a bounded mean of this person's observed errors; model weights never refit.",
                     "80 % prediction ranges (split-conformal), calibrated for the exact serving pipeline.",
                     "Warning score: highest forecast in the next 60 min minus 180 mg/dL — not a probability."]},
        {"kind": "table", "title": "Why this learner: validation-only selection", "table": sel_table,
         "note": (f"Rule: lowest mean per-participant validation MAE over both horizons; within 0.5 mg/dL → simpler model. "
                  f"Only {', '.join(eligible)} (profile + wearable) was eligible, to meet the fusion requirement — a constraint added on {ff['declared_on']}, after the test segment had been inspected. "
                  f"Selected: {m['selection']['selected_label']} with patient correction. Without the constraint the rule picks {bm['selection']['selected_label']} ({base})."
                  if disc and bm else
                  f"Rule: lowest mean per-participant validation MAE over both horizons; within 0.5 mg/dL → simpler model. "
                  f"Selected: {m['selection']['selected_label']} with patient correction; we did not switch after seeing test results.")},
        guardrails_slide(),
        results_overview(m),
        *([foundation_slide()] if foundation_slide() else []),
        {"kind": "bullets", "title": "Project outcomes",
         "bullets": ["Built: a working glucose twin — replay API, immutable forecasts, warnings with outcomes — and a clinician workspace.",
                     "Found: the published 1-minute CGM values are interpolated; we use only native 5-minute readings.",
                     f"Later recordings of the same {n_pt} people: MAE {ss.loc[30, 'mae']:.2f} / {ss.loc[60, 'mae']:.2f} mg/dL vs persistence "
                     f"{mae('persistence:cgm-only-v1', 'off', 30):.2f} / {mae('persistence:cgm-only-v1', 'off', 60):.2f}; "
                     f"better for {better(30)}/{n_pt} people at 30 min and {better(60)}/{n_pt} at 60 min.",
                     f"Warnings: {int(e['detected_onsets'])}/{int(e['true_onsets'])} onsets detected"
                     + (f", {e['false_alarms_per_observed_patient_day']:.2f} false alarms per observed patient-day" if corrected else "")
                     + (f"; {demo_notice30()} of all onsets warned ≥ 30 min ahead." if demo_notice30() else "."),
                     "Reproducible: synthetic mode needs no download; results regenerate from versioned configs."]},
        {"kind": "bullets", "title": "Limitations",
         "bullets": ["14 participants from one US site; no Indian participants.",
                     "Blinded CGMs replayed with assumed zero latency; medication and meal timing unknown.",
                     *(["Profile values are constant per person; no benefit shown for people held out entirely."] if disc else []),
                     f"Ranges under-cover ({ivs[ivs['horizon'] == 30]['coverage'].iloc[0] * 100:.1f} % / {ivs[ivs['horizon'] == 60]['coverage'].iloc[0] * 100:.1f} % vs 80 % target); "
                     "the warning threshold ignores review workload.",
                     "Retrospective replay only — no clinical, workflow or safety study.",
                     "Next: a prospective, consented Indian cohort and a full-fusion evaluation on new people."]},
        {"kind": "bullets", "title": "Team, links, reproducibility and licenses",
         "bullets": [f"{team}. {inst}.",
                     f"Code: {repo} — MIT license (code only). Quick start: make setup · make synthetic · make dev.",
                     f"Demo video: {video}.",
                     "Data: CGMacros 1.0.0 (PhysioNet, doi:10.13026/3z8q-x658, CC BY-NC-SA 4.0); "
                     "ShanghaiT2DM (figshare, doi:10.6084/m9.figshare.21600933.v5, CC BY 4.0).",
                     "Evidence: docs/judge_guide.md · reports/evidence_manifest.md"
                     + (" · docs/submission/GlucoTwin_Research_Workbook.xlsx" if (OUT / "GlucoTwin_Research_Workbook.xlsx").exists() else "")
                     + "."]},
    ]


def build_pptx(deck: list[dict], path: Path) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Inches, Pt

    def rgb(h):
        return RGBColor.from_string(h.lstrip("#"))

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    W = prs.slide_width

    def rule(slide, x, y, w, weight, color=INK):
        ln = slide.shapes.add_connector(1, x, y, x + w, y)
        st = ln._element.find(qn("p:style"))  # no theme style: no shadow, exact weight
        if st is not None:
            ln._element.remove(st)
        ln.line.color.rgb = rgb(color)
        ln.line.width = Pt(weight)

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
        sl.background.fill.solid()
        sl.background.fill.fore_color.rgb = rgb("#FFFFFF")
        if s["kind"] == "title":
            rule(sl, Inches(0.9), Inches(1.75), Inches(1.2), 2.5)
            textbox(sl, Inches(0.9), Inches(2.0), Inches(11), Inches(1.2), s["title"], 54, True)
            textbox(sl, Inches(0.9), Inches(3.2), Inches(11), Inches(0.8), s["subtitle"], 26)
            tf = textbox(sl, Inches(0.9), Inches(4.4), Inches(11), Inches(1.6), s["body"][0], 20, True)
            for line in s["body"][1:]:
                p = tf.add_paragraph()
                r = p.add_run()
                r.text = line
                r.font.size, r.font.name = Pt(18), "Arial"
                r.font.color.rgb = rgb(INK)
            continue
        if s.get("section"):
            textbox(sl, Inches(0.6), Inches(0.14), Inches(12.1), Inches(0.3), s["section"], 11, True, BLUE)
        textbox(sl, Inches(0.6), Inches(0.42 if s.get("section") else 0.35), Inches(12.1), Inches(0.7), s["title"], 30, True)
        rule(sl, Inches(0.6), Inches(1.08), Inches(12.13), 0.75, LIGHT)
        textbox(sl, Inches(12.3), Inches(7.05), Inches(0.5), Inches(0.3), f"{i}", 11)
        if s["kind"] == "architecture":
            draw_pptx(sl, s["spec"])
            continue
        if s["kind"] in ("bullets", "bullets_image"):
            w = Inches(12.1) if s["kind"] == "bullets" else Inches(6.3)
            tb = sl.shapes.add_textbox(Inches(0.6), Inches(1.35), w, Inches(5.6))
            tf = tb.text_frame
            tf.word_wrap = True
            for j, b in enumerate(s["bullets"]):
                p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                r = p.add_run()
                r.text = f"•  {b}"
                r.font.size, r.font.name = Pt((17 if len(s["bullets"]) <= 6 else 15.5) if s["kind"] == "bullets" else 15), "Arial"
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
                textbox(sl, Inches(0.6), Inches(6.45), Inches(12.1), Inches(0.9), s["caption"], 13)
        elif s["kind"] == "results":
            from pptx.util import Inches as In
            widths = [In(2.9), In(5.3), In(1.95), In(1.95)]
            rows = len(s["table"])
            gt = sl.shapes.add_table(rows, 4, In(0.6), In(1.35), sum(widths, In(0)), In(0.46 * rows)).table
            for c_i, w in enumerate(widths):
                gt.columns[c_i].width = w
            for r_i, row in enumerate(s["table"]):
                gt.rows[r_i].height = In(0.46)
                group = row[0].startswith("§")
                if group:
                    gt.cell(r_i, 0).merge(gt.cell(r_i, 3))
                for c_i in range(4):
                    cell = gt.cell(r_i, c_i)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = rgb("#FFFFFF")
                    cell.margin_top = cell.margin_bottom = Pt(3)
                    if group and c_i > 0:
                        continue
                    val = row[0][1:] if group else str(row[c_i])
                    cell.text = val
                    run = cell.text_frame.paragraphs[0].runs[0]
                    run.font.size, run.font.name = Pt(13.5), "Arial"
                    run.font.bold = r_i == 0 or group or (c_i >= 2 and row[1].endswith("(serving)"))
                    run.font.color.rgb = rgb(BLUE if group else INK)
                    run.font.italic = val == PENDING
            textbox(sl, Inches(0.6), Inches(1.35 + 0.46 * rows + 0.6), Inches(12.1), Inches(1.0), s["note"], 14)
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
                    cell.fill.fore_color.rgb = rgb("#FFFFFF")  # white cells, black text
                    para.runs[0].font.color.rgb = rgb(INK)  # the selected row is marked in bold
            textbox(sl, Inches(9.1), Inches(1.35), Inches(3.8), Inches(5.5), s["note"], 14)
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
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=12, leading=16, textColor=HexColor(INK))

    def image(pathstr, x, y, maxw, maxh):
        img = ImageReader(pathstr)
        iw, ih = img.getSize()
        sc = min(maxw / iw, maxh / ih)
        cv.drawImage(img, x + (maxw - iw * sc) / 2, y + (maxh - ih * sc) / 2, iw * sc, ih * sc)

    for i, s in enumerate(deck, start=1):
        if s["kind"] == "architecture":  # full-slide figure drawn from the same spec as the PPTX shapes
            cv.drawImage(ImageReader(s["image"]), 0, 0, W, H)
        if s["kind"] == "title":
            cv.setFillColor(HexColor(INK))
            cv.rect(65, H - 128, 86, 2.5, stroke=0, fill=1)
            cv.setFont("Helvetica-Bold", 54)
            cv.drawString(65, H - 210, s["title"])
            cv.setFont("Helvetica", 26)
            cv.drawString(65, H - 260, s["subtitle"])
            cv.setFont("Helvetica", 18)
            for j, line in enumerate(s["body"]):
                cv.drawString(65, H - 330 - j * 28, line)
            cv.showPage()
            continue
        if s.get("section"):
            cv.setFillColor(HexColor(BLUE))
            cv.setFont("Helvetica-Bold", 11)
            cv.drawString(43, H - 28, s["section"])
        cv.setFillColor(HexColor(INK))
        cv.setFont("Helvetica-Bold", 28)
        cv.drawString(43, H - 70, s["title"])
        cv.setStrokeColor(HexColor(LIGHT))
        cv.setLineWidth(0.75)
        cv.line(43, H - 78, W - 43, H - 78)
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
        elif s["kind"] == "results":
            data, style = [], [("FONT", (0, 0), (-1, -1), "Helvetica", 11), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 11),
                               ("TEXTCOLOR", (0, 0), (-1, -1), HexColor(INK)),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor(LIGHT))]
            for r_i, row in enumerate(s["table"]):
                if row[0].startswith("§"):
                    data.append([row[0][1:], "", "", ""])
                    style += [("SPAN", (0, r_i), (-1, r_i)), ("FONT", (0, r_i), (-1, r_i), "Helvetica-Bold", 11),
                              ("TEXTCOLOR", (0, r_i), (-1, r_i), HexColor(BLUE))]
                else:
                    data.append(row)
            t = Table(data, colWidths=[200, 380, 150, 150])
            t.setStyle(TableStyle(style))
            _, h = t.wrap(W - 86, 400)
            t.drawOn(cv, 43, top - h)
            p = Paragraph(s["note"], small)
            _, h2 = p.wrap(W - 86, 200)
            p.drawOn(cv, 43, top - h - 16 - h2)
        elif s["kind"] == "table":
            t = Table(s["table"], colWidths=[230, 110, 110, 90])
            style = [("FONT", (0, 0), (-1, -1), "Helvetica", 12), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 12),
                     ("TEXTCOLOR", (0, 0), (-1, -1), HexColor(INK)), ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor(LIGHT)),
                     ("LINEBELOW", (0, 0), (-1, 0), 1, HexColor(INK)), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                     ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
            for r_i, row in enumerate(s["table"]):
                if row[0] == SERVING_LABEL:
                    style += [("FONT", (0, r_i), (-1, r_i), "Helvetica-Bold", 12)]
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
        "<b>3. Bounded patient update.</b> AdaptationState adds a shrunk, decaying correction learned only from earlier forecasts whose target readings were already available: at least 6 matured outcomes, capped at ±25 mg/dL, reset after a 3-hour gap. Model weights are never refit.",
        "<b>4. Uncertainty and warning.</b> Split-conformal prediction ranges (target coverage 80 %) calibrated for this exact pipeline; warning score = max forecast within 60 min − 180 mg/dL (uncalibrated, not a probability). Warning outcomes use one shared one-to-one onset matcher offline and in replay.",
        "<b>5. Immutable record and review ledger.</b> Forecasts are stored once under uuid5(session, revision, origin, model version); outcomes are revealed only when the replay clock passes their availability. A clinician's review of a warning (with a note) is written to the SQLite audit; the review summary freezes what was known at its replay cutoff.",
        "<b>6. Revisions.</b> Seek/reset rebuild the twin from released events only; old cursors return 409; the browser keys caches by (session, revision, clock).",
        "<b>Candidates.</b> Research experiments write only their own artifacts and never the model registry; a candidate is served only after every declared release gate, serving parity and integration checks pass, through an explicit promote command with a recorded rollback.",
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


def team_folder(sub: dict) -> Path:
    """The challenge's `Team Name_College Name` folder (e.g. Kryptonite_VESIT/): an index of the submission files.

    The files stay where the README links them, so each exists once; links and status come from configs/submission.yaml.
    """
    t, links = sub["team"], sub["links"]
    d = ROOT / f"{t['name']}_{t['institution_short']}"
    d.mkdir(exist_ok=True)
    video = (f"[{links['video']}]({links['video']})" if links["video"]
             else "Not yet recorded or uploaded; the link is added here and in [README §8](../README.md#8-demo-video) after upload")
    repo = f"[{links['repository']}]({links['repository']})" if links["repository"] else "This repository (public link added after publication)"
    rows = [
        ("Project README: all twelve form items", "[`README.md`](../README.md)"),
        ("Results at a glance (each row names its model and evaluation setting)", "[README](../README.md#results-at-a-glance)"),
        ("Presentation with details and outcomes", "[`GlucoTwin_Presentation.pdf`](../docs/submission/GlucoTwin_Presentation.pdf) · "
                                                   "[`.pptx`](../docs/submission/GlucoTwin_Presentation.pptx)"),
        ("Architecture diagram", "[`GlucoTwin_Architecture.pdf`](../docs/submission/GlucoTwin_Architecture.pdf)"),
        ("Research workbook: every claim mapped to its source, with gates and verification",
         "[`GlucoTwin_Research_Workbook.xlsx`](../docs/submission/GlucoTwin_Research_Workbook.xlsx) · "
         "[method note](../docs/submission/GlucoTwin_Research_Workbook_Methodology.md)"),
        ("Video script and recording checklist", "[`demo_script.md`](../docs/demo_script.md) · "
                                                 "[`GlucoTwin_Demo_Script.pdf`](../docs/submission/GlucoTwin_Demo_Script.pdf)"),
        (f"Demo video (unlisted YouTube, at least {sub['video']['minimum_duration'].split(':')[0]} minutes)", video),
        ("Team details", "[`docs/team_details.md`](../docs/team_details.md)"),
        ("Source code", f"{repo}: [`apps/web`](../apps/web) · [`services/api`](../services/api) · [`ml/glucotwin`](../ml/glucotwin)"),
        ("Run it locally", "[README](../README.md#run-it-locally)"),
        ("License", "[`LICENSE`](../LICENSE) (MIT, code only); data terms in [README §9](../README.md#9-open-source-license)"),
    ]
    text = "\n".join([
        f"# {d.name}: GlucoTwin",
        "",
        f"**{brand(sub)}** · {t['institution']} · Digital Twin Challenge 2026 (Happiest Health).",
        f"Team: {' · '.join(f'{n} (leader)' if n == t['leader'] else n for n in t['members'])}.",
        "",
        "This folder follows the challenge's `Team Name_College Name` rule. It indexes the submission; each file lives",
        "once in the repository, at the path the README links.",
        "",
        "| Item | Where |",
        "|---|---|",
        *[f"| {a} | {b} |" for a, b in rows],
        "",
        "Research demonstration only: not a medical device and no treatment advice. Generated by",
        "[`scripts/build_submission_assets.py`](../scripts/build_submission_assets.py) from",
        "[`configs/submission.yaml`](../configs/submission.yaml).",
        "",
    ])
    (d / "README.md").write_text(text)
    return d / "README.md"


def build_script_pdf(md: Path, path: Path) -> None:
    """Render the narration script (Markdown) to a clean A4 PDF: headings, spoken lines (quoted), tables, lists."""
    import re

    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def inline(t: str) -> str:
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
        t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        return re.sub(r"\*([^*]+)\*", r"<i>\1</i>", t)

    base = ParagraphStyle("p", fontName="Helvetica", fontSize=9.5, leading=13, textColor=HexColor(INK), spaceAfter=5)
    st = {1: ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, spaceAfter=8),
          2: ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=10),
          3: ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=6)}
    quote = ParagraphStyle("q", parent=base, leftIndent=14, fontName="Helvetica", textColor=HexColor(INK),
                           borderPadding=(0, 0, 0, 6))
    cell = ParagraphStyle("c", parent=base, fontSize=8, leading=10, spaceAfter=0)
    story, para, table, quote_buf = [], [], [], []

    def flush():
        if para:
            story.append(Paragraph(inline(" ".join(para)), base))
            para.clear()
        if quote_buf:
            txt = " ".join(quote_buf).replace("\x00", "<br/><br/>")
            story.append(Paragraph(inline(txt).replace("&lt;br/&gt;", "<br/>"), quote))
            quote_buf.clear()
        if table:
            rows = [[Paragraph(inline(c.strip()), cell) for c in r.strip().strip("|").split("|")] for r in table
                    if not re.match(r"^\|[-| ]+\|$", r.strip())]
            n = max(len(r) for r in rows)
            rows = [r + [Paragraph("", cell)] * (n - len(r)) for r in rows]
            t = Table(rows, colWidths=[(A4[0] - 100) / n] * n, repeatRows=1)
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, HexColor(LIGHT)),
                                   ("LINEBELOW", (0, 0), (-1, 0), 0.8, HexColor(INK)), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.extend([t, Spacer(1, 6)])
            table.clear()

    for line in md.read_text().splitlines():
        if line.startswith("|"):
            if para or quote_buf:
                flush()
            table.append(line)
            continue
        if table:
            flush()
        if line.startswith(">"):
            if para:
                flush()
            body = line[1:].strip()
            quote_buf.append(body if body else "\x00")
            continue
        if quote_buf and not line.startswith(">"):
            flush()
        m = re.match(r"^(#{1,3}) (.*)", line)
        if m:
            flush()
            story.append(Paragraph(inline(m.group(2)), st[len(m.group(1))]))
        elif line.strip() == "---":
            flush()
            story.append(Spacer(1, 6))
        elif re.match(r"^(\* |\d+\. )", line):
            flush()
            para.append(("• " if line.startswith("* ") else "") + re.sub(r"^\* ", "", line))
        elif not line.strip():
            flush()
        else:
            if line.startswith("**") and para:  # stage-direction labels (Screen:, Clicks:, Expected …) start new lines
                flush()
            para.append(line.strip())
    flush()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=50, rightMargin=50, topMargin=46, bottomMargin=46,
                            title="GlucoTwin — demonstration video script", author="Team Kryptonite, VESIT")
    doc.build(story)


def export_pdf_from_pptx(pptx: Path) -> bool:
    """Export the PDF from the PPTX with LibreOffice so both files show the same slides with embedded fonts."""
    import shutil
    import subprocess

    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        return False
    r = subprocess.run([office, "--headless", "--convert-to", "pdf", "--outdir", str(pptx.parent), str(pptx)],
                       capture_output=True, text=True, timeout=300)
    ok = r.returncode == 0 and pptx.with_suffix(".pdf").exists()
    print(f"PDF exported from PPTX with LibreOffice: {ok}")
    return ok


def main() -> None:
    global SERVING_LABEL
    ASSETS.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    m = load()
    SERVING_LABEL = serving_ids(m)[0]
    for f in (fig_mae, fig_paired, fig_per_patient):
        print(f(m))
    print(fig_architecture(m))
    print(fig_split())
    print(fig_twin_loop())
    build_architecture_pdf(OUT / "GlucoTwin_Architecture.pdf", m)
    deck = slides(m, submission())
    build_pptx(deck, OUT / "GlucoTwin_Presentation.pptx")
    if not export_pdf_from_pptx(OUT / "GlucoTwin_Presentation.pptx"):
        build_pdf(deck, OUT / "GlucoTwin_Presentation.pdf")  # fallback without LibreOffice: same content, own layout
    print(f"slides: {len(deck)} -> {OUT}")
    build_script_pdf(ROOT / "docs/demo_script.md", OUT / "GlucoTwin_Demo_Script.pdf")
    print(team_folder(submission()))


if __name__ == "__main__":
    main()
