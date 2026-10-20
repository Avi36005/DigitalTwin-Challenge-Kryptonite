"""How much useful notice the reported warnings give, from saved forecasts only (no fit, no assessment re-opened).

For the demo model's 60-minute warning (final test segment, inspected) and the D-043 research warnings at 60 and 120
minutes (people held out, internal validation): onsets detected and missed, the share of ALL eligible onsets warned at
least 15 and 30 minutes ahead (not a median among detected ones), false alarms per observed day, time in warning,
precision and the qualified-lead distribution. Episodes, matching and leads come from the same code as every other
warning in this repository (scripts/warning_time_share.py reuses glucotwin.evaluation.alerts and checks the rebuilt
counts against the saved metrics before reporting).

Usage:  uv run --group docs python scripts/warning_utility.py   (writes reports/warning_utility.md and its figure)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import warning_time_share as WT  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "reports/warning_utility.md"
FIG = ROOT / "reports/warning_utility_leads.png"

_leads: dict[int, list[float]] = {}
_finish = WT.finish


def _keep_leads(m: dict) -> dict:
    leads = list(m.get("leads", []))
    out = _finish(m)
    out["_leads"] = leads
    return out


WT.finish = _keep_leads  # demo() and research() call finish(); keep the qualified leads it would discard


def saved_rates() -> dict[str, float]:
    m = json.loads((ROOT / "artifacts/experiments" / WT.DEMO / "metrics.json").read_text())
    sel = m["selection"]
    name = f"{sel['selected_label']} ({'adaptive' if sel['serving_personalization'] == 'adaptive' else 'population'})"
    e = next(x for x in m["events"] if x["model"] == name and x["split"] == "test" and x["horizon"] == 60)
    out = {"demo": e["false_alarms_per_observed_patient_day"], "demo_precision": e["precision"]}
    s = json.loads((ROOT / "artifacts/research" / WT.RES / "two_hour_summary.json").read_text())
    for w in s["warnings"]:
        if w["pipeline"] == "selected" and w["mode"] == "final":
            out[f"research{w['horizon']}"] = w["false_alarms_per_observed_day"]
            out[f"research{w['horizon']}_precision"] = w["precision"]
    return out


def main() -> int:
    rows = [r for r in WT.demo() if r["key"] == "demo"] + WT.research()
    rates = saved_rates()
    table = []
    for r in rows:
        leads = np.array(r["_leads"], float)
        n = r["onsets"]
        table.append({"key": r["key"], "warning": r["warning"], "where": r["where"], "onsets": n, "detected": r["detected"],
                      "missed": n - r["detected"], "ge15": int((leads >= 15).sum()), "ge30": int((leads >= 30).sum()),
                      "ge60": int((leads >= 60).sum()), "fa_day": rates.get(r["key"]), "precision": rates.get(f"{r['key']}_precision"),
                      "share": r["share_eligible"], "lead_median": r["lead_median"],
                      "lead_q": [float(np.percentile(leads, q)) for q in (25, 75)] if len(leads) else None, "leads": leads})
    pct = lambda a, b: f"{100 * a / b:.1f} %" if b else "—"  # noqa: E731
    md = ["# How much notice the warnings give", "",
          "From saved forecasts only; nothing fitted, no assessment re-opened. Every onset is a new episode above 180 mg/dL "
          "for at least 15 minutes from a below-threshold state; a warning's *qualified lead* is the time from the earliest "
          "firing whose own forecast horizon contains the onset. The share columns use **all** eligible onsets as the "
          "denominator, so a missed onset counts against them — unlike a median lead among detected onsets.", "",
          "| Warning | Evaluated on | Onsets | Detected / missed | Warned ≥ 15 min ahead | ≥ 30 min | ≥ 60 min | False alarms per observed day | Precision | Time in warning | Qualified lead, median (IQR) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in table:
        q = r["lead_q"]
        fa = "—" if r["fa_day"] is None else f"{r['fa_day']:.2f}"
        pr = "—" if r["precision"] is None else f"{r['precision']:.2f}"
        md.append(f"| {r['warning']} | {r['where']} | {r['onsets']} | {r['detected']} / {r['missed']} | {pct(r['ge15'], r['onsets'])} | "
                  f"{pct(r['ge30'], r['onsets'])} | {pct(r['ge60'], r['onsets'])} | {fa} | {pr} | "
                  f"{WT.pct(r['share'])} | {r['lead_median']:.0f} ({q[0]:.0f}–{q[1]:.0f}) min |")
    md += ["", "The demo warning's test segment was inspected, so its row is retrospective; the research rows are people held "
           "out entirely but already inspected (internal validation). A 120-minute horizon does not give 120 minutes of "
           "notice: most two-hour warnings fire shortly before the onset. Different event definitions or denominators "
           "elsewhere do not make a head-to-head comparison.", "", f"![Qualified lead distribution]({FIG.name})", "",
           "Regenerate: `uv run --group docs python scripts/warning_utility.py`.", ""]
    OUT_MD.write_text("\n".join(md))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(table), figsize=(4 * len(table), 3), sharey=False)
    for ax, r in zip(np.atleast_1d(axes), table, strict=True):
        ax.hist(r["leads"], bins=np.arange(0, 125, 5), color="#2563eb")
        ax.set_title({"demo": "Demo model, 60-min warning\n(final test segment)",
                      "research120": "Research, 120-min warning\n(people held out)",
                      "research60": "Research, 60-min warning\n(people held out)"}.get(r["key"], r["key"]), fontsize=8)
        ax.set_xlabel("qualified lead (min)", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("detected onsets", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG, dpi=150)
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
