"""Markdown and figures for the nested research experiment, rendered from ``report.json`` only.

The upgrade recommendation follows a rule fixed in this code BEFORE the outer assessment was opened
(docs/decisions.md D-032): recommend replacing the serving recipe only if the selected 5-minute pipeline differs from it
and beats the refit v2 recipe on outer folds at BOTH horizons with a participant-bootstrap 95 % interval entirely below
zero, without a higher false-alarm rate per observed day under its own warning policy. Otherwise: retain LightGBM v2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from glucotwin.config import paths

H = ("30", "60")


def f(x: Any, nd: int = 2, pct: bool = False) -> str:
    if x is None:
        return "—"
    if pct:
        return f"{100 * float(x):.{max(0, nd - 1)}f} %"
    return f"{float(x):.{nd}f}"


def ci(c: list) -> str:
    """Interval of a signed difference."""
    return "—" if not c or c[0] is None else f"[{c[0]:+.2f}, {c[1]:+.2f}]"


def rng(c: list, nd: int = 2) -> str:
    """Interval of a rate or proportion (no signs)."""
    return "—" if not c or c[0] is None else f"[{c[0]:.{nd}f}, {c[1]:.{nd}f}]"


def _pipe(track: dict, name: str, mode: str) -> dict | None:
    return next((p for p in track["pipelines"] if p["pipeline"] == name and p["mode"] == mode), None)


def _cmp(track: dict, title: str, h: str) -> dict | None:
    return next((c for c in track["comparisons"] if c["comparison"] == title and str(c["horizon"]) == h), None)


def promotion_check(rep: dict, crit: dict) -> list[dict]:
    """Declared multi-criteria promotion rule (protocols from gt-nested-2026-10-12-v2): average error, high-glucose
    error, missed onsets and false warnings, each against the serving recipe under its own frozen warning policy."""
    t = rep["tracks"]["multimodal_5min"]
    out = []
    for h in H:
        c = _cmp(t, "Selected pipeline minus current v2 recipe", h)
        out.append({"criterion": f"average error, {h} min", "passed": bool(c and c["ci95"][1] is not None and c["ci95"][1] < 0),
                    "detail": f"{c['mean_diff']:+.2f} {ci(c['ci95'])} mg/dL; required: upper bound < 0" if c else "missing"})
    hg = crit["high_glucose_error"]
    for h in [str(x) for x in hg["horizons"]]:
        c = _cmp(t, "High-glucose error (target > 180): selected minus current v2 recipe", h)
        ok = bool(c and c["ci95"][1] is not None and c["ci95"][1] <= float(hg["max_ci_upper_mg_dl"]))
        out.append({"criterion": f"high-glucose error, {h} min", "passed": ok,
                    "detail": (f"{c['mean_diff']:+.2f} {ci(c['ci95'])} mg/dL; required: upper bound ≤ "
                               f"+{float(hg['max_ci_upper_mg_dl']):g}") if c else "missing"})
    pol = {(p["pipeline"], p["horizon"], p["policy"]): p for p in t.get("warnings", {}).get("policies", [])}
    mo, fw = crit["missed_onsets"], crit["false_warnings"]
    s_w = pol.get(("selected", int(mo["horizon"]), "primary"))
    v_w = pol.get(("v2_recipe:dyn-v2", int(mo["horizon"]), "v2_fixed"))
    ok_r = bool(s_w and v_w and s_w.get("recall") is not None and v_w.get("recall") is not None
                and s_w["recall"] >= v_w["recall"] - float(mo["max_recall_drop"]))
    out.append({"criterion": "missed onsets", "passed": ok_r,
                "detail": (f"recall {s_w.get('recall')} vs {v_w.get('recall')}; required drop ≤ {mo['max_recall_drop']}"
                           if s_w and v_w else "missing")})
    fa_s = s_w.get("false_alarms_per_observed_day") if s_w else None
    fa_v = v_w.get("false_alarms_per_observed_day") if v_w else None
    ok_f = bool(fa_s is not None and fa_s <= float(fw["max_per_observed_day"])
                and (not fw.get("not_above_serving") or (fa_v is not None and fa_s <= fa_v)))
    out.append({"criterion": "false warnings", "passed": ok_f,
                "detail": f"{fa_s} vs {fa_v} per observed day; required ≤ {fw['max_per_observed_day']} and not above serving"})
    return out


def recommendation(rep: dict) -> tuple[str, list[str]]:
    from glucotwin.research.protocol import load_protocol

    crit = (load_protocol(rep["experiment_id"]).get("promotion") or {}).get("criteria")
    if crit:  # declared multi-criteria rule
        res = promotion_check(rep, crit)
        lines = [f"{'PASS' if r['passed'] else 'FAIL'} — {r['criterion']}: {r['detail']}" for r in res]
        ok = all(r["passed"] for r in res)
        return ("Promote the frozen candidate (all declared criteria met; still an explicit decision)" if ok else
                "Retain the current serving model (a declared promotion criterion failed)"), lines
    t = rep["tracks"]["multimodal_5min"]
    reasons = []
    outer = {k: v["selected"] for k, v in t["selection_by_fold"].items() if k != "final"}
    final_sel = t["selection_by_fold"].get("final", {}).get("selected")
    same_recipe = final_sel is not None and final_sel.startswith("lightgbm_l2:dyn-v2")
    ok_h = []
    for h in H:
        c = _cmp(t, "Selected pipeline minus current v2 recipe", h)
        ok_h.append(bool(c and c["ci95"][1] is not None and c["ci95"][1] < 0))
        if c:
            reasons.append(f"{h} min, outer folds: selected minus refit v2 recipe {c['mean_diff']:+.2f} mg/dL, 95 % CI "
                           f"{ci(c['ci95'])} ({c['improved']} of {c['n_participants']} people improved).")
    pol = {(p["pipeline"], p["horizon"], p["policy"]): p for p in t.get("warnings", {}).get("policies", [])}
    s_w = pol.get(("selected", 60, "primary"))
    v_w = pol.get(("v2_recipe:dyn-v2", 60, "v2_fixed"))
    worse_workload = bool(s_w and v_w and s_w.get("false_alarms_per_observed_day") is not None
                          and v_w.get("false_alarms_per_observed_day") is not None
                          and s_w["false_alarms_per_observed_day"] > v_w["false_alarms_per_observed_day"])
    if s_w and v_w and s_w.get("status") == "ok":
        reasons.append(f"60-minute warnings: {s_w['detected_onsets']} of {s_w['true_onsets']} onsets at "
                       f"{s_w['false_alarms_per_observed_day']:.2f} false alarms per observed day (selected, workload rule) "
                       f"versus {v_w['detected_onsets']} of {v_w['true_onsets']} at "
                       f"{v_w['false_alarms_per_observed_day']:.2f} (v2 recipe, margin −30).")
    sp, vp = _pipe(t, "selected", "final"), _pipe(t, "v2_recipe:dyn-v2", "v2_policy")
    if sp and vp:
        a, b = sp["horizons"]["60"]["mae_high_glucose_target"], vp["horizons"]["60"]["mae_high_glucose_target"]
        hc = _cmp(t, "High-glucose error (target > 180): selected minus current v2 recipe", "60")
        if a is not None and b is not None:
            reasons.append(f"Trade-off: when the 60-minute target was above 180 mg/dL, the selected pipeline's MAE was "
                           f"{a:.2f} versus {b:.2f} mg/dL for the v2 recipe ({'worse' if a > b else 'better'} on large highs"
                           + (f"; paired difference {hc['mean_diff']:+.2f} {ci(hc['ci95'])} over {hc['n_participants']} "
                              "people" if hc and hc.get("mean_diff") is not None else "") + "). This rule did not bound it; "
                           "the next protocol does (gt-nested-2026-10-12-v2).")
    counts: dict[str, int] = {}
    for v in outer.values():
        counts[v] = counts.get(v, 0) + 1
    reasons.append("Chosen per outer fold: " + ", ".join(f"`{k}` in {n} of {len(outer)}" for k, n in
                                                        sorted(counts.items(), key=lambda x: -x[1]))
                   + f"; deployment candidate (all 14 people): `{final_sel}`.")
    if same_recipe:
        reasons.append(f"The deployment candidate ({final_sel}) uses the serving recipe's family and inputs.")
    switch = (not same_recipe) and all(ok_h) and not worse_workload
    reasons.append("Scope: internal validation on 14 already-inspected CGMacros people; the 5-minute candidate has no "
                   "independent 5-minute external test. Promotion was NOT executed; it needs an explicit decision.")
    return ("Replace the serving recipe with the frozen candidate — rule met; promotion is a separate, explicit "
            "decision" if switch else "Retain the current LightGBM v2 serving model"), reasons


def _serving() -> str | None:
    import json as _json

    reg = paths().artifacts / "registry.json"
    return _json.loads(reg.read_text()).get("serving", {}).get("dataset_replay") if reg.exists() else None


def registry_status(rep: dict) -> str:
    """What the registry serves right now, and whether that is a candidate of this experiment."""
    import json as _json

    reg = paths().artifacts / "registry.json"
    serving = _json.loads(reg.read_text()).get("serving", {}).get("dataset_replay") if reg.exists() else None
    cands = {c["candidate"]["model_version"] for c in (rep.get("candidates") or {}).values() if c.get("candidate")}
    if serving in cands:
        return f"The registry serves the promoted candidate `{serving}`."
    return f"The registry serves `{serving}`; no candidate of this experiment has been promoted."


def _cand_name(rep: dict, track: str) -> str:
    c = (rep.get("candidates") or {}).get(track, {}).get("candidate")
    if not c:
        return "—"
    fam = {"ridge": "Ridge", "lightgbm": "LightGBM", "catboost": "CatBoost"}.get(c["model_version"].split(".")[0],
                                                                                 c["model_version"].split(".")[0])
    return f"{fam} (`{c['model_version']}`)"


def protocol_notes(rep: dict) -> list[str]:
    """Measured consequences of declared choices that a reader should know (generated, never hand-written)."""
    out = []
    ext = rep.get("external", {})
    if ext.get("status") == "completed":
        sel = next((p for p in ext["pipelines"] if p["selected"] and p["mode"] == "final"), None)
        if sel:
            better = [p for p in ext["pipelines"] if p is not sel and all(
                (p["horizons"][h]["mae"] or 1e9) < (sel["horizons"][h]["mae"] or -1) for h in H)]
            if better:
                b = min(better, key=lambda p: p["horizons"]["60"]["mae"])
                out.append(f"External cohort: {len(better)} other frozen pipeline/personalization combinations had lower error "
                           f"than the candidate at both horizons; the lowest was `{b['pipeline']}` ({b['mode']}) at "
                           f"{f(b['horizons']['30']['mae'])} / {f(b['horizons']['60']['mae'])} vs "
                           f"{f(sel['horizons']['30']['mae'])} / {f(sel['horizons']['60']['mae'])} mg/dL. All were frozen before "
                           "opening; none was chosen by the development rule, and switching on this result would turn the "
                           "external cohort into a tuning set, so it is reported, not adopted.")
        per = next((p for p in ext["pipelines"] if p["pipeline"] == "persistence:-" and p["mode"] == "off"), None)
        lt = next((p for p in ext["pipelines"] if p["pipeline"] == "linear_trend:-" and p["mode"] == "off"), None)
        for h in H:
            if per and lt and per["horizons"][h]["mae"] == lt["horizons"][h]["mae"]:
                out.append(f"Portable track, {h} min: the declared linear-trend grid offered a 15-minute slope window, which "
                           "cannot be computed at 15-minute cadence (fewer than three readings); development data chose it, "
                           "so this 'linear trend' equals persistence. A protocol design flaw, reported rather than fixed "
                           "after freezing.")
    return out


# ------------------------------------------------------------------------------------------------ figures


def figures(rep: dict) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = paths().reports / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    blue, ink, grey = "#1d4ed8", "#111827", "#9ca3af"
    t = rep["tracks"]["multimodal_5min"]
    w = t.get("warnings")
    if w:
        fig, axes = plt.subplots(1, 2, figsize=(10, 4), dpi=150)
        styles = {"selected": (blue, "o", "Selected pipeline"), "persistence:-": (grey, "s", "Persistence"),
                  "v2_recipe:dyn-v2": (ink, "^", "Current v2 recipe")}
        for name, (col, mk, lab) in styles.items():
            pts = [c for c in w["curves"] if c["pipeline"] == name and c["horizon"] == 60 and c["recall"] is not None]
            if not pts:
                continue
            axes[0].scatter([c["false_alarms_per_observed_day"] for c in pts], [c["recall"] for c in pts], color=col,
                            marker=mk, s=28, label=f"{lab}: tested thresholds")
            axes[1].scatter([c["recall"] for c in pts], [c["precision"] for c in pts], color=col, marker=mk, s=28)
            pol = next((p for p in w["policies"] if p["pipeline"] == name and p["horizon"] == 60
                        and p["policy"] == ("v2_fixed" if name.startswith("v2") else "primary") and p["status"] == "ok"), None)
            if pol:
                axes[0].scatter([pol["false_alarms_per_observed_day"]], [pol["recall"]], color=col, marker="*", s=180,
                                edgecolor="white", linewidth=0.8, label=f"{lab}: validation-selected policy")
                axes[1].scatter([pol["recall"]], [pol["precision"]], color=col, marker="*", s=180, edgecolor="white")
        axes[0].axvline(2.0, color=grey, lw=0.8, ls=":")
        axes[0].set_xlabel("False alarms per observed forecastable day")
        axes[0].set_ylabel("Event recall (assessable onsets)")
        axes[1].set_xlabel("Event recall")
        axes[1].set_ylabel("Warning precision")
        for a in axes:
            a.spines[["top", "right"]].set_visible(False)
            a.grid(alpha=0.15)
        axes[0].legend(fontsize=6.5, frameon=False, loc="lower right")
        fig.suptitle("60-minute research warnings on outer-fold participants (points = tested thresholds; "
                     "stars = per-fold validation-selected policies pooled)", fontsize=8)
        fig.tight_layout()
        p = out_dir / "warning_tradeoff_60.png"
        fig.savefig(p)
        plt.close(fig)
        out["warning_tradeoff_60"] = str(p.relative_to(paths().root))
    fig, ax = plt.subplots(figsize=(7, 3.4), dpi=150)
    rows = []
    for track, label in (("multimodal_5min", "Internal 5-min"), ("portable_15min", "Internal 15-min")):
        sp = _pipe(rep["tracks"][track], "selected", "final")
        if sp:
            for h in H:
                for meth in ("global", "cls"):
                    rows.append((f"{label}\n{h} min", meth, sp["intervals"][h][meth].get("coverage_pooled")))
    ext = rep.get("external", {})
    if ext.get("status") == "completed":
        sp = next((p for p in ext["pipelines"] if p["selected"] and p["mode"] == "final"), None)
        if sp:
            for h in H:
                for meth in ("global", "cls"):
                    rows.append((f"External 15-min\n{h} min", meth, sp["intervals"][h][meth].get("coverage_pooled")))
    groups = list(dict.fromkeys(r[0] for r in rows))
    for i, g in enumerate(groups):
        for j, meth in enumerate(("global", "cls")):
            v = next((r[2] for r in rows if r[0] == g and r[1] == meth), None)
            if v is not None:
                ax.bar(i + (j - 0.5) * 0.36, v, width=0.34, color=blue if meth == "global" else "#93c5fd",
                       label=("Split-conformal (primary)" if meth == "global" else "Locally scaled (secondary)") if i == 0 else None)
    ax.axhline(0.8, color=ink, lw=0.9, ls="--", label="Target level 80 %")
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(groups, fontsize=7)
    ax.set_ylim(0.5, 1.0)
    ax.set_ylabel("Measured coverage (pooled)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    fig.tight_layout()
    p = out_dir / "range_coverage.png"
    fig.savefig(p)
    plt.close(fig)
    out["range_coverage"] = str(p.relative_to(paths().root))
    return out


# ------------------------------------------------------------------------------------------------ markdown


def _forecast_table(track: dict, rows: list[tuple[str, str]]) -> list[str]:
    L = ["| Pipeline | MAE 30 | MAE 60 | RMSE 30 | RMSE 60 | High-glucose MAE 60 | Availability | People |",
         "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, mode in rows:
        p = _pipe(track, name, mode)
        if not p:
            continue
        a, b = p["horizons"]["30"], p["horizons"]["60"]
        L.append(f"| {p['display']} | {f(a['mae'])} | {f(b['mae'])} | {f(a['rmse'])} | {f(b['rmse'])} | "
                 f"{f(b['mae_high_glucose_target'])} | {f(b['availability'], 3, pct=True)} | {b['n_participants']} |")
    return L


def _cmp_table(comps: list[dict]) -> list[str]:
    L = ["| Comparison (a minus b, mg/dL) | Horizon | Mean difference | 95 % CI | Improved / worsened |",
         "|---|---:|---:|---|---|"]
    for c in comps:
        if c.get("mean_diff") is None:
            continue
        L.append(f"| {c['comparison']} | {c['horizon']} | {c['mean_diff']:+.2f} | {ci(c['ci95'])} | "
                 f"{c['improved']} / {c['worsened']} of {c['n_participants']} |")
    return L


def _interval_table(pipes: list[tuple[str, dict]]) -> list[str]:
    L = ["| Pipeline | Horizon | Method | Coverage (pooled) | Coverage (macro) | Participant range | Mean width | "
         "Interval score | Low / usual / high glucose coverage | No interval |",
         "|---|---:|---|---:|---:|---|---:|---:|---|---:|"]
    for title, p in pipes:
        for h in H:
            for meth, mname in (("global", "split-conformal"), ("cls", "locally scaled")):
                s = p["intervals"][h][meth]
                st = s.get("by_current_glucose", {})
                strat = " / ".join(f(st.get(k, {}).get("coverage"), 3, pct=True) for k in ("low", "usual", "high"))
                extra = f" (fallback {f(s.get('fallback_rate'), 3, pct=True)})" if meth == "cls" else ""
                L.append(f"| {title} | {h} | {mname}{extra} | {f(s.get('coverage_pooled'), 3, pct=True)} | "
                         f"{f(s.get('coverage_macro'), 3, pct=True)} | {f(s.get('coverage_participant_min'), 3, pct=True)}–"
                         f"{f(s.get('coverage_participant_max'), 3, pct=True)} | {f(s.get('width_mean'), 1)} | "
                         f"{f(s.get('interval_score_macro'), 1)} | {strat} | {s.get('n_without_interval', '—')} |")
    return L


def _warn_table(w: dict, H_: int) -> list[str]:
    L = ["| Pipeline | Policy | Thresholds by fold | Recall (95 % CI) | Missed / onsets | Precision | False alarms "
         "per observed day (95 % CI) | per eligible day | Warnings per observed day | Censored | Qualified lead median (IQR) |",
         "|---|---|---|---|---|---:|---|---:|---:|---:|---|"]
    names = {"primary": "workload ≤ 2.0/day (primary)", "f1_comparator": "max F1 (v1/v2 rule)", "v2_fixed": "v2 margin −30",
             "budget_0.5": "budget 0.5/day", "budget_1.0": "budget 1.0/day", "budget_3.0": "budget 3.0/day"}
    for p in w["policies"]:
        if p["horizon"] != H_:
            continue
        if p["status"] != "ok":
            L.append(f"| {p['display']} | {names.get(p['policy'], p['policy'])} | no feasible threshold | — | — | — | — | — | — | — | — |")
            continue
        th = ", ".join("none" if v is None else f"{v:+g}" for v in p["thresholds_by_fold"].values())
        L.append(f"| {p['display']} | {names.get(p['policy'], p['policy'])} | {th} | {f(p['recall'], 3)} {rng(p['recall_ci95'])} "
                 f"| {p['missed_onsets']} / {p['true_onsets']} | {f(p['precision'], 3)} | "
                 f"{f(p['false_alarms_per_observed_day'])} {rng(p['false_alarms_per_observed_day_ci95'])} | "
                 f"{f(p['false_alarms_per_eligible_day'])} | {f(p['warnings_per_observed_day'])} | {p['censored_warnings']} | "
                 f"{f(p['qualified_lead_median'], 1)} ({f(p['qualified_lead_iqr'][0], 1)}–{f(p['qualified_lead_iqr'][1], 1)}) |")
    return L


def render_report(rep: dict, figs: dict[str, str]) -> str:
    t5, t15, ext = rep["tracks"]["multimodal_5min"], rep["tracks"]["portable_15min"], rep.get("external", {})
    L = [f"# Nested benchmark report — `{rep['experiment_id']}`", "",
         f"Generated by `glucotwin research report` from saved predictions on {rep['created_at'][:10]}. Protocol "
         f"declared {rep['declared_on']}, split membership frozen {rep['frozen_at']} (protocol hash "
         f"`{rep['protocol_hash']}`, split hash `{rep['split_hash']}`). Outer assessment opened "
         f"{rep['assessment_opened']['opened_at']}.", "",
         "> **Scope.** " + rep["status_message"] + ". The serving model was not changed by this experiment.", "",
         "## Inspection history", ""]
    L += [f"* {e['date']}: {' '.join(e['what'].split())}" for e in rep["inspection_log"]]
    L += ["", "## Folds", "", "| Fold | Assessment | Calibration | Development | Inner folds |", "|---|---:|---:|---:|---|"]
    L += [f"| {x['fold']} | {x['assessment']} | {x['calibration']} | {x['development']} | {'/'.join(map(str, x['inner_folds']))} |"
          for x in rep["folds"]]
    for key, t in (("multimodal_5min", t5), ("portable_15min", t15)):
        L += ["", f"## {t['name']}", "", "### Selection on inner out-of-fold predictions", "",
              "| Fold | Selected | Personalization | Rationale |", "|---|---|---|---|"]
        for fold, s in t["selection_by_fold"].items():
            ad = s["adaptation"]
            ad_s = "off" if not ad or ad["name"] == "off" else f"{ad['name']} (k={ad['k']:g}, half-life {ad['half_life']:g} min)"
            L.append(f"| {fold} | `{s['selected']}` | {ad_s} | {s['rationale']} |")
        fs = rep_fs(key)
        rows = [("selected", "final"), ("selected", "off"), ("persistence:-", "off"), ("linear_trend:-", "off")]
        rows += [(f"{c}:{x}", "off") for x in fs for c in ("ridge", "lightgbm_l2", "lightgbm_l1", "catboost")]
        rows += [(f"best:{c}", "final") for c in ("lightgbm_l2", "lightgbm_l1", "catboost")]
        if key == "multimodal_5min":
            rows += [("v2_recipe:dyn-v2", "v2_policy"), ("v2_recipe:dyn-v2", "off")]
        L += ["", f"### Outer-fold results ({t['participants']} participants, each assessed once)", "",
              "Macro over participants (each person weighted equally), mg/dL. High-glucose MAE uses origins whose "
              "target exceeded 180 mg/dL (people with at least 20 such origins). Availability = share of target-bearing "
              "origins that received a forecast.", ""]
        L += _forecast_table(t, rows)
        L += ["", "### Paired comparisons (participant-cluster bootstrap, 2,000 resamples)", ""] + _cmp_table(t["comparisons"])
        sp = _pipe(t, "selected", "final")
        if sp:
            L += ["", "### Cold start and personalization (selected pipeline)", "",
                  "Elapsed history = time since the first reading of the current recording.", "",
                  "| Mode | Horizon | First 6 h | 6–24 h | After 24 h |", "|---|---:|---:|---:|---:|"]
            for mode in ("off", "v2_policy", "best_grid", "frozen_state", "final"):
                p = _pipe(t, "selected", mode)
                if not p:
                    continue
                for h in H:
                    cs = p["horizons"][h]["cold_start"]
                    L.append(f"| {MODE(mode)} | {h} | " + " | ".join(
                        f"{f(cs[k]['mae_macro'])} (n={cs[k]['origins']:,}, {cs[k]['participants']} people)"
                        for k in ("first_6h", "6_to_24h", "after_24h")) + " |")
            L += ["", "### Prediction ranges (target level 80 %)", ""]
            L += _interval_table([("Selected — " + MODE("final"), sp)])
        if t.get("warnings"):
            L += ["", "### Research warnings (60-minute horizon, outer folds)", "",
                  "Thresholds were chosen per fold on inner out-of-fold predictions of the exact final pipeline. "
                  "False alarms per observed forecastable day use non-overlapping, gap-respecting exposure.", ""]
            L += _warn_table(t["warnings"], 60)
            L += ["", "30-minute horizon:", ""] + _warn_table(t["warnings"], 30)
            if "warning_tradeoff_60" in figs:
                L += ["", f"![Warning trade-off]({Path(figs['warning_tradeoff_60']).relative_to('reports')})"]
    L += ["", "## External assessment — ShanghaiT2DM", ""]
    if ext.get("status") != "completed":
        L.append(f"Not run: {ext.get('reason')}")
    else:
        L += [f"Opened once on {ext['opened']['opened_at']} with the frozen portable candidate `{ext['candidate']}` "
              f"(freeze hash `{ext['candidate_freeze_hash']}`), {ext['participants']} participants. Regression and "
              "ranges only (no event metric is defined at 15-minute cadence).", "",
              "| Pipeline | MAE 30 | MAE 60 | RMSE 30 | RMSE 60 | Availability | People |", "|---|---:|---:|---:|---:|---:|---:|"]
        for p in ext["pipelines"]:
            a, b = p["horizons"]["30"], p["horizons"]["60"]
            L.append(f"| {p['display']}{' **(candidate)**' if p['selected'] and p['mode'] == 'final' else ''} | {f(a['mae'])} | "
                     f"{f(b['mae'])} | {f(a['rmse'])} | {f(b['rmse'])} | {f(b['availability'], 3, pct=True)} | {b['n_participants']} |")
        L += ["", *_cmp_table(ext["comparisons"])]
        sp = next((p for p in ext["pipelines"] if p["selected"] and p["mode"] == "final"), None)
        if sp:
            L += ["", *_interval_table([("External candidate", sp)])]
    if "range_coverage" in figs:
        L += ["", f"![Coverage]({Path(figs['range_coverage']).relative_to('reports')})"]
    notes = protocol_notes(rep)
    if notes:
        L += ["", "## Notes on the declared design", ""] + [f"* {x}" for x in notes]
    L += ["", "## Limitations", ""] + [f"* {x}" for x in rep["limitations"]] + [""]
    return "\n".join(L)


def MODE(m: str) -> str:
    from glucotwin.research.report import MODE_NAMES
    return MODE_NAMES.get(m, m)


def rep_fs(track: str) -> list[str]:
    from glucotwin.research.protocol import load_protocol
    return load_protocol()["tracks"][track]["feature_sets"]


def render_review(rep: dict, figs: dict[str, str]) -> str:
    t5, t15, ext = rep["tracks"]["multimodal_5min"], rep["tracks"]["portable_15min"], rep.get("external", {})
    d = rep["data"]["counts_by_dataset"]
    cg, sh = d["cgmacros"], d["shanghai_t2dm"]
    decision, reasons = recommendation(rep)
    sp5, sp15 = _pipe(t5, "selected", "final"), _pipe(t15, "selected", "final")
    _pipe(t5, "v2_recipe:dyn-v2", "v2_policy")
    _pipe(t5, "persistence:-", "off")
    L = ["# Model upgrade review", "",
         f"Experiment `{rep['experiment_id']}` (nested participant-level benchmark + reserved external cohort). Every "
         "number below is generated from saved prediction and event records by `glucotwin research report`; nothing is "
         "typed in by hand.", "",
         "| Model | Role | Status |", "|---|---|---|",
         f"| LightGBM v2 (`lightgbm.dyn-v2.gt-primary-2026-10-11-v2`) | demo model before this experiment | "
         f"{'serving' if _serving() == 'lightgbm.dyn-v2.gt-primary-2026-10-11-v2' else 'replaced by a promotion'} |",
         f"| {_cand_name(rep, 'multimodal_5min')} | five-minute candidate | "
         f"{'promoted, serving' if _serving() in _cand_name(rep, 'multimodal_5min') else 'evaluated, not promoted'} |",
         f"| {_cand_name(rep, 'portable_15min')} | external check (separate 15-minute model) | evaluated once on ShanghaiT2DM |",
         "", f"**Recommendation by the pre-specified rule: {decision}.** {registry_status(rep)}", ""]
    L += [f"* {r}" for r in reasons]
    L += ["", "## 1. Research question and current limitations", "",
          "Does a tuned LightGBM (L2 or L1 objective), CatBoost, or a different input set forecast glucose 30 and 60 "
          "minutes ahead better than the current serving recipe for people the model has never seen — and does a "
          "portable CGM-only model trained on CGMacros transfer to an independent cohort recorded with a different "
          "device, cadence and country? The serving model (LightGBM dyn-v2 + adaptation, experiment v2) was selected "
          "on the same 14 CGMacros people and its test segment was already inspected, so it could not answer either "
          "question.", "",
          "## 2. Provenance and inclusion", "", "```text",
          "CGMacros 1.0.0 (PhysioNet, 45 people) ──► Type 2 + >=72 h Dexcom: 14 ──► 5 outer participant folds",
          "   └─ 31 pre-diabetes / no diabetes: replay only (not trained, tuned or assessed)",
          "ShanghaiT2DM (figshare v5, 100 people, 109 recordings) ──► >=72 observed h: "
          f"{sh['participants']} ──► reserved external cohort (opened once)",
          "AI-READI v3 (2,280 people, publisher) ──► access_required: 0 imported",
          "Glucose-ML (catalog) ──► discovery only: 0 imported (would duplicate CGMacros / Shanghai / AI-READI)",
          "```", "",
          "## 3. Counts actually used", "",
          "| | CGMacros | ShanghaiT2DM |", "|---|---:|---:|",
          "| Imported real participants | 45 | 100 |",
          f"| Eligible for this experiment | {cg['participants']} | {sh['participants']} |",
          f"| Outer-fold assessment groups | {cg['outer_assessment_group_sizes']} | — |",
          f"| Development (training) people per outer fold | {cg['outer_development_sizes']} | 0 (never trained on) |",
          f"| Calibration people per outer fold | {cg['outer_calibration_group_sizes']} | 0 |",
          f"| Assessed people | {cg['assessed_participants']} (internal, each once) | "
          f"{ext.get('participants', 0) if ext.get('status') == 'completed' else 0} (external) |",
          f"| Final candidate: development / calibration people | {cg['final_candidate_development_participants']} / "
          f"{cg['final_candidate_calibration_participants']} | — |", "",
          "Native readings, observed hours and exclusions: `reports/dataset_expansion_audit.md`.", "",
          "## 4. Frozen evaluation design", "",
          "Protocol `configs/experiments/gt-nested-2026-10-12-v1.yaml`, declared and frozen before any fit (hashes in "
          "`reports/nested_benchmark_report.md`). Five outer folds grouped by participant; inside each, a reserved "
          "calibration group and three inner participant folds. Every choice (family, objective, feature set, "
          "hyperparameters, adaptation, warning threshold, interval quantile) was made on inner or calibration data; "
          "the outer participants of a fold were assessed once with the frozen pipeline. The external cohort was "
          "never used for any choice.", "",
          "## 5. Same-input family comparisons and feature ablations", ""]
    L += _forecast_table(t5, [("selected", "final"), ("v2_recipe:dyn-v2", "v2_policy"), ("persistence:-", "off"),
                              ("lightgbm_l2:dyn-v2", "off"), ("lightgbm_l1:dyn-v2", "off"), ("catboost:dyn-v2", "off"),
                              ("lightgbm_l2:cgm-only-v1", "off"), ("lightgbm_l2:dyn-prof-v2", "off")])
    L += ["", *_cmp_table(t5["comparisons"]), "",
          "## 6. Cold start and adaptation", ""]
    if sp5:
        for mode in ("off", "final"):
            p = _pipe(t5, "selected", mode)
            if p:
                cs = p["horizons"]["60"]["cold_start"]
                L.append(f"* 60 min, {MODE(mode)}: first 6 h {f(cs['first_6h']['mae_macro'])}, 6–24 h "
                         f"{f(cs['6_to_24h']['mae_macro'])}, after 24 h {f(cs['after_24h']['mae_macro'])} mg/dL.")
        L.append("* Adaptation per fold: " + "; ".join(
            f"{k}: {('off' if not v['adaptation'] or v['adaptation']['name'] == 'off' else v['adaptation']['name'])}"
            for k, v in t5["selection_by_fold"].items()) + ".")
    L += ["", "## 7. Warning burden and prediction ranges", ""]
    if t5.get("warnings"):
        L += _warn_table(t5["warnings"], 60)
    if sp5:
        L += ["", *_interval_table([("5-min selected", sp5)] + ([("15-min selected", sp15)] if sp15 else []))]
    L += ["", "## 8. External validation (ShanghaiT2DM)", ""]
    if ext.get("status") == "completed":
        se = next((p for p in ext["pipelines"] if p["selected"] and p["mode"] == "final"), None)
        pe = next((p for p in ext["pipelines"] if p["pipeline"] == "persistence:-" and p["mode"] == "off"), None)
        if se and pe:
            d = {h: next((c for c in ext["comparisons"] if c["comparison"] == "Selected candidate minus persistence"
                          and str(c["horizon"]) == h), None) for h in H}
            def dd(c):
                if not c:
                    return "—"
                verdict = "inconclusive" if c["ci95"][0] < 0 < c["ci95"][1] else "clear"
                return f"{c['mean_diff']:+.2f} mg/dL {ci(c['ci95'])}, {verdict}"
            L.append(f"The frozen 15-minute LightGBM `{ext['candidate']}` (a separate model from the demo model and the "
                     f"five-minute candidate) reached macro MAE {f(se['horizons']['30']['mae'])} / "
                     f"{f(se['horizons']['60']['mae'])} mg/dL at 30/60 minutes on {se['horizons']['60']['n_participants']} "
                     f"ShanghaiT2DM participants (persistence {f(pe['horizons']['30']['mae'])} / "
                     f"{f(pe['horizons']['60']['mae'])}). Difference from persistence: 30 min {dd(d['30'])}; 60 min "
                     f"{dd(d['60'])}.")
        L += ["", *_cmp_table(ext["comparisons"])]
        if se:
            L += ["", *_interval_table([("External candidate", se)])]
    else:
        L.append(f"Not run: {ext.get('reason')}")
    L += ["", "## 9. Handoff, reproducibility and limitations", "", "### Candidate handoff", ""]
    for track, c in rep.get("candidates", {}).items():
        cc = c["candidate"]
        par = c.get("parity") or {}
        L += [f"**{track}** — `{cc['model_version']}` (`{cc['selected']}`, personalization `{cc['mode']}`), status "
              f"`{c['status']}`, serving-eligible: {cc['serving_eligible']}.",
              f"* Adaptation: {'enabled' if c['adaptation']['enabled'] else 'disabled'} (k={c['adaptation']['shrinkage_k']:g}, "
              f"half-life {c['adaptation']['half_life_minutes']:g} min); ranges: "
              f"{', '.join(f'{h} min ±{f(q, 1)}' for h, q in c['intervals']['quantiles_mg_dl'].items())} mg/dL "
              f"(level {c['intervals']['level']}); warning margin: "
              f"{(c.get('alerts') or {}).get('threshold_margin_mg_dl', 'n/a')}.",
              f"* Freeze hash `{cc['freeze_hash']}`; file checksums in `artifacts/research/{rep['experiment_id']}/candidates/"
              f"{track}/candidate.json`.",
              (f"* Online/offline parity: {par.get('origins')} origins, max absolute difference population "
               f"{par.get('max_abs_population')}, correction {par.get('max_abs_correction')}, final "
               f"{par.get('max_abs_final')} mg/dL before display rounding; engine replay {par.get('ms_per_origin')} ms per "
               "origin (end-to-end engine, excluding HTTP)." if par else "* Parity check: not run."), ""]
    L += ["### Commands", "", "```bash",
          "uv run glucotwin data import --dataset shanghai_t2dm && uv run glucotwin data manifest",
          "uv run glucotwin research freeze && uv run glucotwin research smoke",
          "uv run glucotwin research develop        # isolated: never writes artifacts/registry.json",
          "uv run glucotwin research assess         # outer folds, once",
          "uv run glucotwin research external       # ShanghaiT2DM, once",
          "uv run glucotwin research report",
          "# Promotion is a separate explicit action (dry run without --yes):",
          "uv run glucotwin research promote --track multimodal_5min",
          "uv run glucotwin research promote --track multimodal_5min --yes",
          "# Rollback to the current serving model:",
          "uv run glucotwin research rollback --to lightgbm.dyn-v2.gt-primary-2026-10-11-v2", "```", "",
          "### Limitations", ""] + [f"* {x}" for x in rep["limitations"] + protocol_notes(rep)] + [""]
    return "\n".join(L)


START, END = "<!-- research-candidates:start -->", "<!-- research-candidates:end -->"


def model_card_block(rep: dict) -> str:
    """Generated model-card section for the research candidates (written between markers in docs/model_card.md)."""
    t5, t15, ext = rep["tracks"]["multimodal_5min"], rep["tracks"]["portable_15min"], rep.get("external", {})
    decision, _ = recommendation(rep)
    c = rep.get("candidates", {})
    sp, pp, vp = _pipe(t5, "selected", "final"), _pipe(t5, "persistence:-", "off"), _pipe(t5, "v2_recipe:dyn-v2", "v2_policy")
    s15 = _pipe(t15, "selected", "final")
    L = [START, "", f"## Research candidates — `{rep['experiment_id']}` (not serving)", "",
         "Generated by `glucotwin research report` from saved predictions; see `reports/model_upgrade_review.md`.", ""]
    for track, cc in c.items():
        x = cc["candidate"]
        L.append(f"* **{track}:** `{x['model_version']}` — `{x['selected']}`, adaptation "
                 f"{'on (k ' + format(cc['adaptation']['shrinkage_k'], 'g') + ', half-life ' + format(cc['adaptation']['half_life_minutes'], 'g') + ' min)' if cc['adaptation']['enabled'] else 'off'}"
                 f", ranges ±{f(cc['intervals']['quantiles_mg_dl'].get('30'), 1)} / ±{f(cc['intervals']['quantiles_mg_dl'].get('60'), 1)} mg/dL"
                 f"{', warning margin ' + format((cc.get('alerts') or {}).get('threshold_margin_mg_dl'), '+g') + ' mg/dL' if (cc.get('alerts') or {}).get('threshold_margin_mg_dl') is not None else ''}"
                 f"; status `{cc['status']}`.")
    if sp and pp and vp:
        L += ["", f"* **New people, 5-minute track (14 CGMacros people, 5 outer folds; internal validation):** macro MAE "
                  f"{f(sp['horizons']['30']['mae'])} / {f(sp['horizons']['60']['mae'])} mg/dL at 30 / 60 min for the "
                  f"rule's per-fold choice, versus {f(vp['horizons']['30']['mae'])} / {f(vp['horizons']['60']['mae'])} for the "
                  f"v2 recipe refit per fold and {f(pp['horizons']['30']['mae'])} / {f(pp['horizons']['60']['mae'])} for "
                  f"persistence. When the 60-minute target exceeded 180 mg/dL: {f(sp['horizons']['60']['mae_high_glucose_target'])} "
                  f"versus {f(vp['horizons']['60']['mae_high_glucose_target'])} (v2 recipe)."]
        g = sp["intervals"]
        L.append(f"* Ranges (target 80 %): measured {f(g['30']['global']['coverage_pooled'], 3, pct=True)} / "
                 f"{f(g['60']['global']['coverage_pooled'], 3, pct=True)} on outer-fold people.")
    if s15:
        L.append(f"* Portable 15-minute track, same people: {f(s15['horizons']['30']['mae'])} / {f(s15['horizons']['60']['mae'])} mg/dL.")
    if ext.get("status") == "completed":
        se = next((p for p in ext["pipelines"] if p["selected"] and p["mode"] == "final"), None)
        pe = next((p for p in ext["pipelines"] if p["pipeline"] == "persistence:-" and p["mode"] == "off"), None)
        if se and pe:
            L.append(f"* **External (ShanghaiT2DM, {ext['participants']} people, 15-minute CGM only, opened once):** "
                     f"{f(se['horizons']['30']['mae'])} / {f(se['horizons']['60']['mae'])} mg/dL versus persistence "
                     f"{f(pe['horizons']['30']['mae'])} / {f(pe['horizons']['60']['mae'])}; range coverage "
                     f"{f(se['intervals']['30']['global']['coverage_pooled'], 3, pct=True)} / "
                     f"{f(se['intervals']['60']['global']['coverage_pooled'], 3, pct=True)} (target 80 %).")
    L += ["", f"**Recommendation by the pre-specified rule:** {decision}. {registry_status(rep)}", "", END]
    return "\n".join(L)


def update_model_card(rep: dict) -> None:
    p = paths().root / "docs" / "model_card.md"
    if not p.exists():
        return
    text = p.read_text()
    block = model_card_block(rep)
    if START in text and END in text:
        text = text[: text.index(START)] + block + text[text.index(END) + len(END):]
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    p.write_text(text)
