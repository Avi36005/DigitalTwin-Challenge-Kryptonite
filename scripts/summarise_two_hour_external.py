"""Summarise the external two-hour check (gt-2h-ext-2026-10-20, decision D-045) from its saved ShanghaiT2DM assessment.

Uses the nested report's own external-cohort function (per-participant pooling, paired participant bootstrap), so the
numbers are comparable with gt-nested-2026-10-12-v1's external results. `glucotwin research report` is not used: it
writes the v1 report files.

Usage:  uv run python scripts/summarise_two_hour_external.py   (after develop, assess and external for gt-2h-ext-2026-10-20)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from glucotwin.research.protocol import load_frozen, load_protocol, research_dir
from glucotwin.research.report import _external

ROOT = Path(__file__).resolve().parents[1]
EXP = "gt-2h-ext-2026-10-20"
OUT_MD = ROOT / "reports/two_hour_external.md"
HS = [30, 60, 120]


def main() -> int:
    proto = load_protocol(EXP)
    x = _external(EXP, proto, int(proto["evaluation"]["bootstrap_resamples"]), int(proto["random_seed"]), HS)
    cand = x["candidate"]
    pipe = {(p["pipeline"], p["mode"]): p for p in x["pipelines"]}
    label = cand.get("label") if isinstance(cand, dict) else cand
    mode = (cand.get("mode") if isinstance(cand, dict) else None) or "final"
    sel = pipe.get((label, mode)) or next(p for (n, m), p in pipe.items() if n == label)
    per = next(p for (n, _), p in pipe.items() if n.startswith("persistence"))
    comp = {c["horizon"]: c for c in x["comparisons"] if c["comparison"] == "Selected candidate minus persistence"}
    pers = {c["horizon"]: c for c in x["comparisons"]
            if c["comparison"] == "Selected candidate: personalization minus population only"}
    cov = lambda p, h: ((p.get("intervals") or {}).get(str(h)) or {}).get("global", {}).get("coverage_pooled")  # noqa: E731
    doc = load_frozen(EXP)
    s = {"experiment_id": EXP, "participants": x["participants"], "opened": x["opened"], "candidate": label,
         "mode": sel["mode"], "freeze_hash": x.get("candidate_freeze_hash"), "split_hash": doc["split_hash"],
         "mae": {h: sel["horizons"][str(h)]["mae"] for h in HS},
         "persistence_mae": {h: per["horizons"][str(h)]["mae"] for h in HS},
         "minus_persistence": {h: {"mean_diff": comp[h]["mean_diff"], "ci95": comp[h]["ci95"],
                                   "improved": comp[h]["improved"], "n": comp[h]["n_participants"]} for h in HS},
         "personalisation": {h: {"mean_diff": pers[h]["mean_diff"], "ci95": pers[h]["ci95"]} for h in HS if h in pers},
         "coverage": {h: cov(sel, h) for h in HS}}
    (research_dir(EXP) / "two_hour_external_summary.json").write_text(json.dumps(s, indent=1, default=str))
    f = lambda c: f"{c['mean_diff']:+.2f} [{c['ci95'][0]:+.2f}, {c['ci95'][1]:+.2f}]"  # noqa: E731
    opened = s["opened"].get("opened_at") if isinstance(s["opened"], dict) else s["opened"]
    md = [f"# Two hours ahead on an independent cohort — `{EXP}`", "",
          "Research experiment (decision D-045), declared before any fit on 20 Oct 2026. The 15-minute CGM-only portable "
          "procedure of `gt-nested-2026-10-12-v1` with a 120-minute horizon, developed on the 14 CGMacros Type 2 people only "
          f"and assessed once on {s['participants']} ShanghaiT2DM people (China, FreeStyle Libre H, 15-minute readings), "
          f"opened at {opened}. No 120-minute result had been computed on this cohort before; it is the cohort's second "
          "opening (the first was for 30/60 minutes). Nothing was chosen on it; not the demo model; nothing promoted.", "",
          f"Candidate: `{label}` ({sel['mode']}), freeze hash `{s['freeze_hash']}`.", "",
          "| Horizon | Candidate MAE (mg/dL) | Persistence MAE | Candidate minus persistence (95 % participant bootstrap) | People better | Range coverage (target 80 %) |",
          "|---|---|---|---|---|---|"]
    for h in HS:
        c = s["minus_persistence"][h]
        cv = s["coverage"][h]
        md.append(f"| {h} min | {s['mae'][h]:.2f} | {s['persistence_mae'][h]:.2f} | {f(c)} | {c['improved']} of {c['n']} | "
                  f"{'—' if cv is None else f'{100 * cv:.1f} %'} |")
    if s["personalisation"]:
        md += ["", "Personalisation (the same candidate with minus without the patient correction): "
               + "; ".join(f"{h} min {f(v)}" for h, v in s["personalisation"].items()) + " mg/dL."]
    md += ["", "CGM only: ShanghaiT2DM has no wearable data, so this checks the forecasting core, not the fusion. Ranges are "
           "wider than needed on this cohort (coverage above the 80 % target).", "",
           "Regenerate: `uv run python scripts/summarise_two_hour_external.py`. Raw numbers: "
           f"`artifacts/research/{EXP}/two_hour_external_summary.json`.", ""]
    OUT_MD.write_text("\n".join(md))
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
