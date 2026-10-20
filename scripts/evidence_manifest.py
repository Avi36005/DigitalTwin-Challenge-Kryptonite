"""Evidence manifest: every headline claim in README.md, traced to the saved artifact it comes from and re-checked.

For each claim the script records the model or procedure, population, horizon, kind of evaluation, protocol and split
identifiers, the artifact and the report, then re-reads the artifact, formats each number the way the README states it
and compares it with the number the README actually states. Status per claim:

* ``matches artifact``  — every stated number equals the artifact's value at the README's rounding;
* ``MISMATCH``          — at least one stated number differs (both values listed);
* ``not found in README`` — the sentence carrying the number was not found (wording changed: update this script);
* ``artifact missing``  — the saved file is not on this installation (git-ignored artifacts; run the experiment);
* ``author-reported``   — a statement this script cannot re-derive from a saved file (named, never counted as checked).

Every artifact-backed row also records the sha256 of each artifact file it read (``artifact_sha256``), so a later reader
can tell whether the file behind a checked number has changed. Rows marked ``pending_readme`` belong to a study whose
README wording has not been written yet; they report ``artifact missing`` or ``not found in README`` until it is, and
never count as checked.

Nothing is fitted and no assessment is re-opened. Numbers are never copied into the web app from here.

Usage:  uv run python scripts/evidence_manifest.py   (writes reports/evidence_manifest.md and .json)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
README = ROOT / "README.md"
OUT_MD = ROOT / "reports/evidence_manifest.md"
OUT_JSON = ROOT / "reports/evidence_manifest.json"

FUSION = "gt-primary-2026-10-13-fusion"
NESTED = "gt-nested-2026-10-12-v1"
TWO_H = "gt-2h-2026-10-20"
TWO_H_EXT = "gt-2h-ext-2026-10-20"
CLF = "gt-2h-clf-2026-10-20"
WARN = "gt-warn-range-2026-10-20"
JOINT = "gt-joint-2026-10-21"


def num(x: float, d: int) -> str:
    return f"{x:.{d}f}"


def sgn(x: float, d: int) -> str:
    """Signed number as the README writes it: + for positive, the minus sign U+2212 for negative."""
    return f"{x:+.{d}f}".replace("-", "−")


def pct(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f}"


def load(path: Path) -> Any:
    return json.loads(path.read_text())


class Missing(Exception):
    pass


def need(path: Path) -> Any:
    if not path.exists():
        raise Missing(str(path.relative_to(ROOT)))
    return load(path)


# --------------------------------------------------------------------------- artifact readers

def fusion() -> dict:
    return need(ART / "experiments" / FUSION / "metrics.json")


def fusion_mae(m: dict, label: str, pers: str, h: int) -> float:
    return next(r["mae"] for r in m["forecast_results"]
                if r["label"] == label and r["personalization"] == pers and r["split"] == "test" and r["horizon"] == h)


def fusion_event(m: dict, model: str, h: int) -> dict:
    return next(e for e in m["events"] if e["model"] == model and e["split"] == "test" and e["horizon"] == h)


def fusion_cov(m: dict, h: int) -> float:
    return next(i["coverage"] for i in m["intervals"] if i["label"] == "lightgbm:dyn-prof-v2"
                and i["personalization"] == "adaptive" and i["split"] == "test" and i["horizon"] == h)


def nested() -> dict:
    return need(ART / "research" / NESTED / "report.json")


def nested_pipe(r: dict, name: str, mode: str, track: str = "multimodal_5min") -> dict:
    pl = r["external"]["pipelines"] if track == "external" else r["tracks"][track]["pipelines"]
    return next(p for p in pl if p["pipeline"] == name and p["mode"] == mode)


def nested_cmp(r: dict, title: str, h: int, track: str = "multimodal_5min") -> dict:
    cs = r["external"]["comparisons"] if track == "external" else r["tracks"][track]["comparisons"]
    return next(c for c in cs if c["comparison"] == title and c["horizon"] == h)


def time_share() -> float:
    """Share of eligible origins at which the demo model's 60-minute warning fires, recomputed from saved predictions
    by scripts/warning_time_share.py (which checks itself against the saved warning metrics before returning)."""
    if not (ART / "experiments" / FUSION / "predictions.parquet").exists():
        raise Missing(f"artifacts/experiments/{FUSION}/predictions.parquet")
    sys.path.insert(0, str(ROOT / "scripts"))
    import warning_time_share  # noqa: PLC0415

    return next(r for r in warning_time_share.demo() if r["key"] == "demo")["share_eligible"]


# --------------------------------------------------------------------------- claims
# Each check: (label, artifact value formatted as the README writes it, regex whose group 1 is the README's number).

Check = tuple[str, str, str]


def c_demo_forecast() -> list[Check]:
    m = fusion()
    a = lambda h: num(fusion_mae(m, "lightgbm:dyn-prof-v2", "adaptive", h), 2)  # noqa: E731
    p = lambda h: num(fusion_mae(m, "persistence:cgm-only-v1", "off", h), 2)  # noqa: E731
    return [("MAE 30", a(30), r"MAE \*\*([\d.]+) / [\d.]+\*\* at 30 / 60 min"),
            ("MAE 60", a(60), r"MAE \*\*[\d.]+ / ([\d.]+)\*\* at 30 / 60 min"),
            ("persistence 30", p(30), r"at 30 / 60 min \(persistence ([\d.]+) /"),
            ("persistence 60", p(60), r"at 30 / 60 min \(persistence [\d.]+ / ([\d.]+)\)")]


def c_demo_warning() -> list[Check]:
    e = fusion_event(fusion(), "lightgbm:dyn-prof-v2 (adaptive)", 60)
    return [("onsets warned", str(int(e["detected_onsets"])), r"\*\*(\d+) of \d+\*\* new high-glucose onsets warned"),
            ("onsets", str(int(e["true_onsets"])), r"\*\*\d+ of (\d+)\*\* new high-glucose onsets warned"),
            ("false alarms", str(int(e["false_alarm_episodes"])), r"\*\*(\d+) false alarms, [\d.]+ per observed patient-day"),
            ("false alarms per observed day", num(e["false_alarms_per_observed_patient_day"], 2),
             r"\*\*\d+ false alarms, ([\d.]+) per observed patient-day"),
            ("median forecast lead", num(e["qualified_lead_median"], 0),
             r"per observed patient-day\*\*; median forecast lead (\d+) min")]


def c_time_share() -> list[Check]:
    return [("share of eligible times warning", pct(time_share()), r"the warning is active at ([\d.]+) % of eligible times")]


def c_demo_ranges() -> list[Check]:
    m, r = fusion(), nested()
    cov = lambda h: pct(nested_pipe(r, "selected", "final")["intervals"][str(h)]["global"]["coverage_pooled"])  # noqa: E731
    return [("demo coverage 30", pct(fusion_cov(m, 30)), r"covered \*\*([\d.]+) % / [\d.]+ %\*\*: under-coverage"),
            ("demo coverage 60", pct(fusion_cov(m, 60)), r"covered \*\*[\d.]+ % / ([\d.]+) %\*\*: under-coverage"),
            ("nested research coverage 30", cov(30), r"calibrated on people held out, covered ([\d.]+) % /"),
            ("nested research coverage 60", cov(60), r"calibrated on people held out, covered [\d.]+ % / ([\d.]+) %")]


def c_nested() -> list[Check]:
    r = nested()
    s, p = nested_pipe(r, "selected", "final"), nested_pipe(r, "persistence:-", "off")
    folds = r["tracks"]["multimodal_5min"]["selection_by_fold"]
    ridge = sum(1 for k, v in folds.items() if k.startswith("outer") and v["selected"] == "ridge:cgm-only-v1")
    return [("MAE 30", num(s["horizons"]["30"]["mae"], 2), r"MAE \*\*([\d.]+) / [\d.]+\*\* \(persistence [\d.]+ / [\d.]+\) \| Research candidate"),
            ("MAE 60", num(s["horizons"]["60"]["mae"], 2), r"MAE \*\*[\d.]+ / ([\d.]+)\*\* \(persistence [\d.]+ / [\d.]+\) \| Research candidate"),
            ("persistence 30", num(p["horizons"]["30"]["mae"], 2), r"\(persistence ([\d.]+) / [\d.]+\) \| Research candidate"),
            ("persistence 60", num(p["horizons"]["60"]["mae"], 2), r"\(persistence [\d.]+ / ([\d.]+)\) \| Research candidate"),
            ("folds choosing Ridge CGM-only", str(ridge), r"Ridge on CGM only, chosen in (\d) of 5 folds")]


def c_external() -> list[Check]:
    r = nested()
    cand = r["external"]["candidate"]
    s, p = nested_pipe(r, cand, "final", "external"), nested_pipe(r, "persistence:-", "off", "external")
    c60 = nested_cmp(r, "Selected candidate minus persistence", 60, "external")
    word = "inconclusive" if c60["ci95"][0] <= 0 <= c60["ci95"][1] else "clear"
    tail = r"\(persistence [\d.]+ / [\d.]+; the 60-minute"
    return [("MAE 30", num(s["horizons"]["30"]["mae"], 2), r"MAE \*\*([\d.]+) / [\d.]+\*\* " + tail),
            ("MAE 60", num(s["horizons"]["60"]["mae"], 2), r"MAE \*\*[\d.]+ / ([\d.]+)\*\* " + tail),
            ("persistence 30", num(p["horizons"]["30"]["mae"], 2), r"\(persistence ([\d.]+) / [\d.]+; the 60-minute"),
            ("persistence 60", num(p["horizons"]["60"]["mae"], 2), r"\(persistence [\d.]+ / ([\d.]+); the 60-minute"),
            ("60-minute difference", word, r"the 60-minute difference is (\w+)")]


def c_profile_nested() -> list[Check]:
    r = nested()
    c = lambda h: nested_cmp(r, "Profile inputs: LightGBM L2 dyn-prof-v2 minus dyn-v2", h)  # noqa: E731
    ci = lambda x: f"{sgn(x['mean_diff'], 2)} [{sgn(x['ci95'][0], 2)}, {sgn(x['ci95'][1], 2)}]"  # noqa: E731
    return [("profile minus no profile, 30 min", ci(c(30)), r"`dyn-v2`: ([+−][\d.]+ \[[+−][\d.]+, [+−][\d.]+\]) mg/dL at 30 min"),
            ("profile minus no profile, 60 min", ci(c(60)),
             r"`dyn-v2`: [+−][\d.]+ \[[+−][\d.]+, [+−][\d.]+\] mg/dL at 30 min and ([+−][\d.]+ \[[+−][\d.]+, [+−][\d.]+\]) at 60 min")]


def two_hour() -> dict:
    return need(ART / "research" / TWO_H / "two_hour_summary.json")


def c_two_hour() -> list[Check]:
    s = two_hour()
    f = s["forecasts"]
    sel = next(c for c in s["comparisons"] if c["comparison"] == "Selected (personalised) minus persistence"
               and c["horizon"] == 120)
    w = next(x for x in s["warnings"] if x["pipeline"] == "selected" and x["horizon"] == 120)
    pre = r"\*\*Two hours ahead:\*\* "
    return [("MAE 120", num(f["selected|final"]["horizons"]["120"]["mae"], 1), pre + r"MAE \*\*([\d.]+)\*\* at 120 min"),
            ("persistence 120", num(f["persistence:-|off"]["horizons"]["120"]["mae"], 1),
             pre + r"MAE \*\*[\d.]+\*\* at 120 min \(persistence ([\d.]+);"),
            ("people better", f"{sel['better_for']} of {sel['participants']}", r"\(persistence [\d.]+; better for (\d+ of \d+) people\)"),
            ("onsets warned", f"{w['detected_onsets']} of {w['true_onsets']}", r"2-hour warning: \*\*(\d+ of \d+)\*\* onsets"),
            ("false alarms per observed day", num(w["false_alarms_per_observed_day"], 2),
             r"2-hour warning: \*\*\d+ of \d+\*\* onsets at \*\*([\d.]+)\*\*"),
            ("median lead (IQR)", f"{num(w['qualified_lead_median'], 0)} min (IQR {num(w['qualified_lead_iqr'][0], 0)}–"
             f"{num(w['qualified_lead_iqr'][1], 0)})", r"median forecast lead (\d+ min \(IQR \d+–\d+\)); ranges covered"),
            ("coverage 120", pct(f["selected|final"]["coverage"]["120"]), r"\(IQR \d+–\d+\); ranges covered ([\d.]+) %"),
            ("profile ablation 120 (LightGBM)", (lambda c: f"{sgn(c['mean_difference'], 2)} [{sgn(c['ci95'][0], 2)}, "
                                                           f"{sgn(c['ci95'][1], 2)}]")(
                next(c for c in s["comparisons"] if c["horizon"] == 120
                     and c["comparison"] == "Profile (EHR-like) inputs: LightGBM dyn-prof-v2 minus dyn-v2")),
             r"\(`gt-2h-2026-10-20`, D-043\): ([+−][\d.]+ \[[+−][\d.]+, [+−][\d.]+\]) mg/dL")]


def c_two_hour_ext() -> list[Check]:
    e = need(ART / "research" / TWO_H_EXT / "two_hour_external_summary.json")
    c = e["minus_persistence"]["120"]
    pre = r"\*\*Two hours ahead, independent cohort:\*\* "
    return [("MAE 120", num(e["mae"]["120"], 2), pre + r"MAE \*\*([\d.]+)\*\* at 120 min"),
            ("persistence 120", num(e["persistence_mae"]["120"], 2), pre + r"MAE \*\*[\d.]+\*\* at 120 min \(persistence ([\d.]+);"),
            ("difference (95 % CI)", f"{sgn(c['mean_diff'], 2)} [{sgn(c['ci95'][0], 2)}, {sgn(c['ci95'][1], 2)}]",
             r"persistence [\d.]+; ([+−][\d.]+ \[[+−][\d.]+, [+−][\d.]+\]) mg/dL, better for"),
            ("people better", f"{c['improved']} of {c['n']}", r"mg/dL, better for \*\*(\d+ of \d+)\*\* people"),
            ("MAE 30 / 60", f"{num(e['mae']['30'], 2)} / {num(e['mae']['60'], 2)}", r"people\); ([\d.]+ / [\d.]+) at 30 / 60 min"),
            ("persistence 30 / 60", f"{num(e['persistence_mae']['30'], 2)} / {num(e['persistence_mae']['60'], 2)}",
             r"at 30 / 60 min \(persistence ([\d.]+ / [\d.]+)\); ranges covered"),
            ("coverage 120", pct(e["coverage"]["120"], 0), r"\(persistence [\d.]+ / [\d.]+\); ranges covered (\d+) %")]


def c_classifier() -> list[Check]:
    r = need(ART / "research" / CLF / "summary.json")["results"]["selected"]
    pre = r"looked perfect on episode counts \("
    return [("onsets warned", f"{r['detected_onsets']} of {r['true_onsets']}", pre + r"(\d+ of \d+) onsets"),
            ("false alarms per day", num(r["false_alarms_per_observed_day"], 2), pre + r"\d+ of \d+ onsets, ([\d.]+) false alarms"),
            ("share of eligible time warning", pct(r["share_of_eligible_time_warning"], 0),
             r"made it warn at (\d+) % of eligible times"),
            ("ROC AUC", num(r["origin_roc_auc"], 2), r"its ROC AUC was (\d+\.\d+)")]


def warn_range() -> dict:
    return need(ART / "research" / WARN / "summary.json")


def c_d046_ranges() -> list[Check]:
    r = warn_range()["ranges"]
    b0, b1 = r["B0_calibration"], r["B1_pooled"]
    return [("coverage 120 before", pct(b0["120"]["coverage_pooled"]), r"brought two-hour coverage from ([\d.]+) % to"),
            ("coverage 120 after", pct(b1["120"]["coverage_pooled"]), r"brought two-hour coverage from [\d.]+ % to \*\*([\d.]+) %\*\*"),
            ("coverage 60 before → after", f"{pct(b0['60']['coverage_pooled'])} → {pct(b1['60']['coverage_pooled'])}",
             r"\(target 80 %; 60 min ([\d.]+ → [\d.]+) %\)"),
            ("width increase", num(b1["120"]["width_mean"] - b0["120"]["width_mean"], 0), r"\), ranges (\d+) mg/dL wider"),
            ("per-person median coverage 120", pct(b1["120"]["coverage_participant_median"]),
             r"per-person median ([\d.]+) %\)")]


def c_d046_warning() -> list[Check]:
    s = warn_range()
    d, w = s["warning_diff_selected_minus_incumbent"], s["warnings"]
    ci = (f"{sgn(100 * d['early_share_diff'], 1)} points [{sgn(100 * d['early_share_ci95'][0], 1)}, "
          f"{sgn(100 * d['early_share_ci95'][1], 1)}]")
    return [("warned ≥ 30 min ahead, selected vs incumbent", f"{w['selected']['early']} vs {w['incumbent']['early']} of "
             f"{w['incumbent']['onsets']}", r"at the same workload \((\d+ vs \d+ of \d+),"),
            ("difference (95 % CI)", ci, r"at the same workload \(\d+ vs \d+ of \d+, ([+−][\d.]+ points \[[+−][\d.]+, [+−][\d.]+\])"),
            ("median lead", num(w["selected"]["lead_median"], 0), r"median lead still (\d+) min")]


def c_d046_profile() -> list[Check]:
    p = warn_range()["profile_prior"]
    c = lambda x: f"{sgn(x['mean_diff'], 2)} [{sgn(x['ci95'][0], 2)}, {sgn(x['ci95'][1], 2)}]"  # noqa: E731
    return [("120 min", c(p["all"]["120"]["c1_minus_population"]),
             r"starting correction changed 120-minute error by ([+−][\d.]+ \[[+−][\d.]+, [+−][\d.]+\]) mg/dL"),
            ("120 min, first 24 h", c(p["first_24h"]["120"]["c1_minus_population"]),
             r"\(first 24 hours: ([+−][\d.]+ \[[+−][\d.]+, [+−][\d.]+\])\)")]


def c_scale() -> list[Check]:
    inv = need(ROOT / "reports" / "dataset_inventory.json")
    imported = sum(d.get("parsed_participants") or 0 for d in inv["datasets"])
    a = inv["assessed_participants_by_dataset"]
    return [("imported", str(imported), r"\*\*(\d+) participants imported;"),
            ("evaluated internally", str(a["cgmacros"]), r"participants imported; (\d+) evaluated internally"),
            ("evaluated externally", str(a["shanghai_t2dm"]), r"evaluated internally and (\d+) evaluated externally\.\*\*")]


def c_serving_identity() -> list[Check]:
    reg = need(ART / "registry.json")
    return [("serving model (recorded data)", reg["serving"]["dataset_replay"],
             r"\*\*LightGBM `dyn-prof-v2` \+ patient adaptation\*\* \(`([^`]+)`\)")]


def c_parity() -> list[Check]:
    p = need(ROOT / "reports" / "serving_parity.json")
    reg = need(ART / "registry.json")
    ok = (p["outcome"] == "pass" and p["over_tolerance"] == 0 and p["missing_online"] == 0
          and p["model_version"] == reg["serving"]["dataset_replay"])
    return [("forecasts compared (saved parity run, outcome pass for the serving model)",
             f"{p['compared']:,}" if ok else f"outcome {p['outcome']}", r"reproduced all ([\d,]+) saved test forecasts"),
            ("tolerance (mg/dL)", f"{p['tolerance_mg_dl']:g}", r"saved test forecasts within ([\d.]+) mg/dL")]


def c_ranges() -> list[Check]:
    s = need(ART / "research" / "gt-ranges-2026-10-21" / "summary.json")
    t = s["test_retrospective"]
    inc, pool = t["incumbent_G_calibration"], t["G_pooled"]
    kept = "served ranges stay" if s["pre_test_check"]["chosen"] == "G" else "trend ranges adopted"
    return [("candidate coverage 30 / 60 (G on validation + calibration, test, retrospective)",
             f"{pct(pool['30']['coverage'])} % / {pct(pool['60']['coverage'])}",
             r"that range covered ([\d.]+ % / [\d.]+) % at 30 / 60 min"),
            ("served coverage 30 / 60", f"{pct(inc['30']['coverage'])} % / {pct(inc['60']['coverage'])}",
             r"against ([\d.]+ % / [\d.]+) % for the\s+served ranges"),
            ("decision", kept, r"so the (served ranges stay) as they are")]


def c_tune() -> list[Check]:
    d = need(ART / "research" / "gt-tune-2026-10-21" / "summary.json")
    a, p = d["arms"], d["paired"]
    c = p["C1_with_history|C0_current_features|final|60"]
    r = p["C1_with_history|R0_untuned_serving_recipe|final|60"]
    ci = lambda x: f"{sgn(x['mean_diff'], 2)} [{sgn(x['ci95'][0], 2)}, {sgn(x['ci95'][1], 2)}]"  # noqa: E731
    return [("C0 / C1 60-min MAE", f"{num(a['C0_current_features']['60']['mae'], 2)} to {num(a['C1_with_history']['60']['mae'], 2)}",
             r"lowered\s+personalised 60-minute error from ([\d.]+ to [\d.]+) mg/dL"),
            ("C1 − C0 (internal)", ci(c), r"error from [\d.]+ to [\d.]+ mg/dL: ([−+\-][\d.]+ \[[−+\-][\d.]+, [−+\-][\d.]+\])"),
            ("people better", f"{c['improved']} of {c['n']}", r"−0\.\d+ \[[^\]]+\], lower for (\d+ of \d+) people"),
            ("C1 − refitted serving recipe (not established)", ci(r),
             r"the\s+difference is ([−+\-][\d.]+ \[[−+\-][\d.]+, [−+\-][\d.]+\])"),
            ("adoption", "not adopted" if not d["adoption"]["c1_better"] else "adopted", r"so C1 is\s+(not adopted)")]


# D-052 (joint model + correction selection). PLACEHOLDER: the README sentence for this study has not been written yet.
# The checks below expect it in exactly the form returned by ``readme_sentence_d052()`` (generated from the saved
# summary, so the lead can paste it); until then these rows are ``not found in README`` (or ``artifact missing`` while
# the study runs) and are flagged ``pending_readme``. If the wording changes, change these patterns with it.
D052_RX = {
    "s_mae": r"personalised 60-minute error ([\d.]+) mg/dL for the selected procedure",
    "r0_mae": r"for the selected procedure vs ([\d.]+) for the refitted serving recipe",
    "diff": r"\(S − R0 ([−+\-][\d.]+ \[[−+\-][\d.]+, [−+\-][\d.]+\])\)",
    "gate": r"\(S − R0 [^)]*\); primary gate (passed|not met)",
    "guardrails": r"primary gate (?:passed|not met); release guardrails (passed|not met|not evaluated)",
    "range": r"candidate 80 % range covered ([\d.]+) % at 60 min",
}


def joint() -> dict:
    return need(ART / "research" / JOINT / "summary.json")


def _d052_values(d: dict) -> dict[str, str]:
    P, g = d["procedures"], d["gate"]
    ci = f"{sgn(g['mean_diff_60'], 2)} [{sgn(g['ci95_60'][0], 2)}, {sgn(g['ci95_60'][1], 2)}]"
    rg = d.get("release_guardrails")
    return {"s_mae": num(P["S"]["60"]["mae"], 2), "r0_mae": num(P["R0"]["60"]["mae"], 2), "diff": ci,
            "gate": "passed" if g["passed"] else "not met",
            "guardrails": "not evaluated" if not rg else ("passed" if rg["passed"] else "not met"),
            "range": pct(d["ranges"]["S"]["60"]["coverage"])}


def readme_sentence_d052() -> str:
    """The README sentence the D-052 checks expect, filled from the saved summary (raises Missing until it exists)."""
    v = _d052_values(joint())
    return (f"personalised 60-minute error {v['s_mae']} mg/dL for the selected procedure vs {v['r0_mae']} for the refitted "
            f"serving recipe (S − R0 {v['diff']}); primary gate {v['gate']}; release guardrails {v['guardrails']}; "
            f"candidate 80 % range covered {v['range']} % at 60 min.")


def c_joint_forecast() -> list[Check]:
    v = _d052_values(joint())
    return [("S 60-min personalised MAE", v["s_mae"], D052_RX["s_mae"]),
            ("R0 60-min personalised MAE (refitted serving recipe)", v["r0_mae"], D052_RX["r0_mae"]),
            ("S − R0 at 60 min (participant bootstrap)", v["diff"], D052_RX["diff"]),
            ("primary gate", v["gate"], D052_RX["gate"])]


def c_joint_operational() -> list[Check]:
    v = _d052_values(joint())
    return [("release guardrails vs R0", v["guardrails"], D052_RX["guardrails"]),
            ("candidate 80 % range coverage, 60 min", v["range"], D052_RX["range"])]


def c_synthetic() -> list[Check]:
    reg = need(ART / "registry.json")
    sid = reg["serving"]["synthetic_demo"]
    entry = next(m for m in reg["models"] if m["model_version"] == sid)
    return [(f"{sid} fitted on fictional data (registry synthetic_fitted)",
             "fitted on fictional data" if entry.get("synthetic_fitted") else "registry does not mark it synthetic",
             r"synthetic demonstration model (fitted on fictional data)")]


# id, claim, model/procedure, population, horizon, evaluation type, protocol, split-hash reader, artifact, report, checks
CLAIMS: list[dict[str, Any]] = [
    dict(id="serving-identity", claim="The app serves the fusion model named in the README (recorded data)",
         model="registry serving entry for dataset_replay", population="—", horizon="30, 60 min", type="software configuration",
         protocol=f"configs/experiments/{FUSION}.yaml", artifact="artifacts/registry.json", report="README.md §7",
         fn=c_serving_identity),
    dict(id="demo-forecast", claim="Demo model forecast error vs persistence",
         model="lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion (fusion LightGBM + patient adaptation)",
         population="14 CGMacros Type 2 people, later recordings of the same people (final test segment)", horizon="30, 60 min",
         type="inspected-test retrospective", protocol=f"configs/experiments/{FUSION}.yaml",
         artifact=f"artifacts/experiments/{FUSION}/metrics.json", report="reports/evaluation_report.md", fn=c_demo_forecast),
    dict(id="demo-warning", claim="Demo model 60-minute research warning", model="same demo model, margin −10 mg/dL",
         population="same as above", horizon="60 min", type="inspected-test retrospective",
         protocol=f"configs/experiments/{FUSION}.yaml", artifact=f"artifacts/experiments/{FUSION}/metrics.json",
         report="reports/evaluation_report.md", fn=c_demo_warning),
    dict(id="demo-time-in-warning", claim="Demo warning active share of eligible times (post-hoc diagnostic)",
         model="same demo model", population="same as above", horizon="60 min", type="inspected-test retrospective",
         protocol=f"configs/experiments/{FUSION}.yaml",
         artifact=f"artifacts/experiments/{FUSION}/predictions.parquet (via scripts/warning_time_share.py)",
         report="reports/warning_time_share.md", fn=c_time_share),
    dict(id="demo-ranges", claim="Demo model ranges under-cover (target 80 %); research procedure for comparison",
         model="same demo model; nested research procedure (selected, personalised)",
         population="demo: final test segment; research: 14 people each held out once", horizon="30, 60 min",
         type="inspected-test retrospective (demo); participant-held-out internal (research)",
         protocol=f"configs/experiments/{FUSION}.yaml; configs/experiments/{NESTED}.yaml",
         artifact=f"artifacts/experiments/{FUSION}/metrics.json; artifacts/research/{NESTED}/report.json",
         report="reports/evaluation_report.md; reports/nested_benchmark_report.md", fn=c_demo_ranges, split=NESTED),
    dict(id="nested-forecast", claim="Research candidate procedure forecast error vs persistence",
         model="per-fold selected pipeline (Ridge CGM-only in most folds), v2 patient update",
         population="14 CGMacros Type 2 people, each held out entirely once", horizon="30, 60 min",
         type="participant-held-out internal", protocol=f"configs/experiments/{NESTED}.yaml",
         artifact=f"artifacts/research/{NESTED}/report.json", report="reports/nested_benchmark_report.md", fn=c_nested,
         split=NESTED),
    dict(id="external-15min", claim="Separate 15-minute LightGBM on an independent cohort",
         model="lightgbm_l2:cgm15-v1 (CGM only), personalised", population="98 ShanghaiT2DM people", horizon="30, 60 min",
         type="external cohort", protocol=f"configs/experiments/{NESTED}.yaml",
         artifact=f"artifacts/research/{NESTED}/report.json", report="reports/nested_benchmark_report.md", fn=c_external,
         split=NESTED),
    dict(id="profile-ablation-nested", claim="Profile (EHR-like) inputs on people held out: no reliable benefit",
         model="LightGBM L2 dyn-prof-v2 minus dyn-v2 (population)", population="14 people each held out once",
         horizon="30, 60 min", type="participant-held-out internal", protocol=f"configs/experiments/{NESTED}.yaml",
         artifact=f"artifacts/research/{NESTED}/report.json", report="reports/nested_benchmark_report.md",
         fn=c_profile_nested, split=NESTED),
    dict(id="two-hour", claim="Two hours ahead: forecast, warning, ranges, profile ablation (D-043)",
         model="per-fold selected CGM-only pipeline (Ridge or LightGBM), personalised", population="14 people each held out once",
         horizon="120 min (warning: max of 30/60/120)", type="participant-held-out internal",
         protocol=f"configs/experiments/{TWO_H}.yaml", artifact=f"artifacts/research/{TWO_H}/two_hour_summary.json",
         report="reports/two_hour_benchmark.md", fn=c_two_hour, split=TWO_H),
    dict(id="two-hour-external", claim="Two hours ahead on an independent cohort (D-045)",
         model="lightgbm_l2:cgm15-v1 re-fitted with a 120-minute horizon (CGM only)", population="98 ShanghaiT2DM people",
         horizon="30, 60, 120 min", type="external cohort", protocol=f"configs/experiments/{TWO_H_EXT}.yaml",
         artifact=f"artifacts/research/{TWO_H_EXT}/two_hour_external_summary.json", report="reports/two_hour_external.md",
         fn=c_two_hour_ext, split=TWO_H_EXT),
    dict(id="classifier-negative", claim="Negative result: direct two-hour onset classifier rejected (D-044)",
         model="LightGBM classifier, fixed settings", population="14 people each held out once (folds of D-043)",
         horizon="onset within 120 min", type="participant-held-out internal (negative result)",
         protocol=f"configs/experiments/{CLF}.yaml", artifact=f"artifacts/research/{CLF}/summary.json",
         report="reports/two_hour_classifier.md", fn=c_classifier, split=TWO_H),
    dict(id="d046-ranges", claim="Ranges calibrated on pooled development people reach the 80 % target (D-046 B)",
         model="two-hour procedure's saved predictions, re-analysed", population="same 14 already-inspected people",
         horizon="60, 120 min", type="re-analysis (internal validation)", protocol=f"configs/experiments/{WARN}.yaml",
         artifact=f"artifacts/research/{WARN}/summary.json", report="reports/warning_range_experiment.md",
         fn=c_d046_ranges, split=TWO_H),
    dict(id="d046-earlier-warning", claim="Negative result: earlier two-hour warning not reliably shown (D-046 A)",
         model="inner-fold-selected warning arm and threshold", population="same 14 already-inspected people",
         horizon="120 min", type="re-analysis (internal validation, negative result)",
         protocol=f"configs/experiments/{WARN}.yaml", artifact=f"artifacts/research/{WARN}/summary.json",
         report="reports/warning_range_experiment.md", fn=c_d046_warning, split=TWO_H),
    dict(id="d046-profile-prior", claim="Negative result: health record as starting correction not shown (D-046 C)",
         model="ridge on 8 profile values + population forecast", population="same 14 already-inspected people",
         horizon="120 min", type="re-analysis (internal validation, negative result)",
         protocol=f"configs/experiments/{WARN}.yaml", artifact=f"artifacts/research/{WARN}/summary.json",
         report="reports/warning_range_experiment.md", fn=c_d046_profile, split=TWO_H),
    dict(id="scale", claim="Participants imported and evaluated", model="—",
         population="CGMacros (45 imported, 14 Type 2 evaluated) and ShanghaiT2DM (100 imported, 98 evaluated)",
         horizon="—", type="data inventory", protocol=f"configs/experiments/{NESTED}.yaml",
         artifact="reports/dataset_inventory.json", report="reports/dataset_expansion_audit.md", fn=c_scale),
    dict(id="ranges-d050", claim="Serving ranges: pooled calibration is a research candidate; served ranges unchanged",
         model="serving pipeline lightgbm:dyn-prof-v2 (adaptive), point forecasts fixed; candidate ranges only",
         population="14 CGMacros people, final test segment (inspected; retrospective)", horizon="30, 60 min",
         type="inspected-test retrospective (candidate, not serving)", protocol="configs/experiments/gt-ranges-2026-10-21.yaml",
         artifact="artifacts/research/gt-ranges-2026-10-21/summary.json", report="reports/serving_ranges_study.md", fn=c_ranges),
    dict(id="tune-d051", claim="Tuned 24-hour history: small internal gain vs equally tuned C0, not adopted",
         model="research LightGBM C0 / C1 / refitted serving recipe R0 (not serving)",
         population="14 CGMacros people, each held out once (previously inspected)", horizon="60 min",
         type="participant-held-out internal", protocol="configs/experiments/gt-tune-2026-10-21.yaml",
         split=TWO_H, artifact="artifacts/research/gt-tune-2026-10-21/summary.json", report="reports/tune_study.md", fn=c_tune),
    dict(id="joint-d052-forecast", claim="Joint model + correction selection vs the refitted serving recipe (D-052)",
         model="nested selected procedure S (family J0/J1/J2 chosen inside each fold) vs refitted serving recipe R0; research candidate, not serving",
         population="14 CGMacros Type 2 people, each held out once (previously inspected)", horizon="60 min",
         type="participant-held-out internal (research candidate)", protocol=f"configs/experiments/{JOINT}.yaml",
         split=TWO_H, artifact=f"artifacts/research/{JOINT}/summary.json", report="reports/joint_study.md",
         fn=c_joint_forecast, pending_readme=True),
    dict(id="joint-d052-operational", claim="D-052 candidate: warning release guardrails and 80 % range coverage",
         model="nested selected procedure S, thresholds chosen on inner folds, ranges on calibration people; research candidate",
         population="14 CGMacros Type 2 people, each held out once (previously inspected)", horizon="60 min",
         type="participant-held-out internal (research candidate)", protocol=f"configs/experiments/{JOINT}.yaml",
         split=TWO_H, artifact=f"artifacts/research/{JOINT}/summary.json", report="reports/joint_study.md",
         fn=c_joint_operational, pending_readme=True),
    dict(id="parity", claim="App replay reproduced all 15,440 saved test forecasts within 0.05 mg/dL",
         model="demo model online (TwinEngine) vs offline", population="final test segment, 14 people", horizon="30, 60 min",
         type="software test", protocol=f"configs/experiments/{FUSION}.yaml", artifact="reports/serving_parity.json",
         report="reports/serving_parity.md", fn=c_parity),
    dict(id="synthetic", claim="Synthetic demonstration model is fitted on fictional data, never evidence",
         model="synthetic-demo.lightgbm.dyn-v2.v1", population="fictional synthetic participants", horizon="30, 60 min",
         type="synthetic", protocol="configs/synthetic.yaml", artifact="artifacts/registry.json",
         report="README.md (Public demonstration)", fn=c_synthetic),
]

AUTHOR_REPORTED: list[dict[str, Any]] = []


def split_hash(eid: str | None) -> str:
    if not eid:
        return "—"
    p = ART / "research" / eid / "splits.json"
    if not p.exists():
        return "missing"
    d = load(p)
    return (d.get("split_hash") or "—")[:12]


def artifact_paths(spec: str) -> list[str]:
    """Repository-relative file paths named in an ``artifact`` field ("a; b (via script)" -> ["a", "b"])."""
    return [part.strip().split(" (")[0].strip() for part in spec.split(";") if part.strip()]


def sha256_of(rel: str) -> str | None:
    p = ROOT / rel
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def evaluate(readme: str) -> list[dict]:
    text = re.sub(r"\s+", " ", readme)
    out = []
    for c in CLAIMS:
        row = {k: v for k, v in c.items() if k not in ("fn", "split")}
        row["split_hash"] = split_hash(c.get("split"))
        row["artifact_sha256"] = {a: sha256_of(a) for a in artifact_paths(c["artifact"])}
        try:
            checks = c["fn"]()
        except Missing as exc:
            row.update(status="artifact missing", checks=[], detail=f"{exc} not on this installation")
            out.append(row)
            continue
        results, worst = [], "matches artifact"
        for label, value, rx in checks:
            m = re.search(rx, text)
            stated = next((g for g in m.groups() if g is not None), None) if m else None
            if m is None:
                res, worst = "not found in README", ("MISMATCH" if worst == "MISMATCH" else "not found in README")
            elif stated == value:
                res = "matches"
            else:
                res, worst = "MISMATCH", "MISMATCH"
            results.append({"label": label, "artifact": value, "readme": stated, "result": res})
        row.update(status=worst, checks=results)
        out.append(row)
    for a in AUTHOR_REPORTED:
        out.append({**a, "split_hash": "—", "status": "author-reported", "checks": [],
                    "detail": "a one-off replay through TwinEngine recorded in the report, not saved as a file; "
                              "`uv run pytest tests/test_v2_preserved.py` re-checks offline that the saved model bundles "
                              "reproduce their saved adaptive forecasts"})
    return out


def render(rows: list[dict]) -> str:
    n = len(rows)
    ok = sum(r["status"] == "matches artifact" for r in rows)
    bad = [r for r in rows if r["status"] == "MISMATCH"]
    pending = sum(1 for r in rows if r.get("pending_readme") and r["status"] != "matches artifact")
    md = ["# Evidence manifest", "",
          "Selected headline claims in the README (not every number in it), each traced to the saved file it comes from. Generated by "
          "`scripts/evidence_manifest.py`, which re-reads each artifact, formats each number the way the README states it "
          "and compares the two. Evaluation types are kept apart: *inspected-test retrospective* (later recordings of people "
          "the model was trained on, test segment already seen), *participant-held-out internal* (people held out entirely, "
          "but already inspected in earlier experiments), *external cohort*, *re-analysis* (saved predictions re-used), "
          "*synthetic* and *software test*. None of them is clinical validation.", "",
          f"**{ok} of {n} claims match their artifacts; {len(bad)} mismatch; "
          f"{sum(r['status'] == 'artifact missing' for r in rows)} artifact(s) missing on this installation; "
          f"{sum(r['status'] == 'author-reported' for r in rows)} author-reported only; "
          f"{pending} awaiting README wording.**", "",
          "| Claim | Model / procedure | Population | Horizon | Evaluation type | Protocol · split | Artifact | Report | Status |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        shas = " ".join(f"sha256 `{h[:12]}`" if h else "(file missing)" for h in (r.get("artifact_sha256") or {}).values())
        status = r["status"] + (" (pending README wording)" if r.get("pending_readme") and r["status"] != "matches artifact" else "")
        md.append(f"| {r['claim']} | {r['model']} | {r['population']} | {r['horizon']} | {r['type']} | "
                  f"`{r['protocol']}` · {r['split_hash']} | `{r['artifact']}` {shas} | {r['report']} | **{status}** |")
    md += ["", "## Numbers checked", "", "| Claim | Number | Artifact | README | Result |", "|---|---|---|---|---|"]
    for r in rows:
        for c in r["checks"]:
            md.append(f"| {r['id']} | {c['label']} | {c['artifact']} | {c['readme'] if c['readme'] is not None else '—'} | "
                      f"{c['result']} |")
        if r.get("detail"):
            md.append(f"| {r['id']} | — | — | — | {r['detail']} |")
    md += ["", "Regenerate: `uv run python scripts/evidence_manifest.py`. Machine-readable copy: "
           "`reports/evidence_manifest.json`.", ""]
    return "\n".join(md)


def main() -> int:
    rows = evaluate(README.read_text())
    OUT_JSON.write_text(json.dumps({"claims": rows}, indent=1, ensure_ascii=False) + "\n")
    md = render(rows)
    OUT_MD.write_text(md)
    print(md)
    return 1 if any(r["status"] == "MISMATCH" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
