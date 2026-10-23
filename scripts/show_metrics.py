"""Print the headline metrics of the serving model straight from the saved files (read-only; for the demo video).

    uv run python scripts/show_metrics.py

Every number is read from artifacts/ or reports/ at run time; nothing is computed from new data. Evaluated on later
recordings of the same 14 CGMacros people (final test segment, retrospective) unless a line says otherwise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "artifacts" / "experiments" / "gt-primary-2026-10-13-fusion" / "metrics.json"


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> None:
    if not EXP.exists():
        raise SystemExit(f"missing {EXP.relative_to(ROOT)} — run `make data experiment` first (recorded data)")
    m = json.loads(EXP.read_text())
    serving = json.loads((ROOT / "artifacts" / "registry.json").read_text())["serving"].get("dataset_replay")
    test = m["cohort"]["by_segment"]["test"]

    print("GlucoTwin — saved evaluation of the serving model")
    print(f"Serving model : {serving}")
    print(f"Evaluated on  : later recordings of the same {m['cohort']['participants']} people "
          f"(final test segment, retrospective) — about {test['covered_hours']:.0f} h, "
          f"{test['distinct_new_onsets_60']} new high-glucose onsets")
    print(f"Source        : {EXP.relative_to(ROOT)}")

    rule("Forecast error (MAE, mg/dL) — lower is better")
    rows = {(r["label"], r["personalization"], r["horizon"]): r["mae"]
            for r in m["forecast_results"] if r["split"] == "test"}
    print(f"{'':46}{'30 min':>9}{'60 min':>9}")
    for name, key in [("GlucoTwin (fusion LightGBM + patient update)", ("lightgbm:dyn-prof-v2", "adaptive")),
                      ("Persistence (last reading carried forward)", ("persistence:cgm-only-v1", "off")),
                      ("Linear trend", ("linear_trend:cgm-only-v1", "off"))]:
        print(f"{name:46}{rows[(*key, 30)]:9.2f}{rows[(*key, 60)]:9.2f}")

    rule("Prediction ranges — target 80 % coverage")
    for r in m["intervals"]:
        if (r["split"], r["label"], r["personalization"]) == ("test", "lightgbm:dyn-prof-v2", "adaptive"):
            print(f"{r['horizon']} min: measured {100 * r['coverage']:.1f} %  "
                  f"(per person {100 * r['per_patient_min']:.1f}–{100 * r['per_patient_max']:.1f} %) — under-covers")

    rule("60-minute research warning (new episode > 180 mg/dL for >= 15 min)")
    ev = next(e for e in m["events"] if e["split"] == "test" and e["model"] == "lightgbm:dyn-prof-v2 (adaptive)"
              and e["horizon"] == 60)
    print(f"Onsets warned          : {ev['detected_onsets']} of {ev['true_onsets']}")
    print(f"False alarms           : {ev['false_alarm_episodes']} episodes = "
          f"{ev['false_alarms_per_observed_patient_day']:.2f} per observed patient-day")
    print(f"Median forecast lead   : {ev['lead_time_median']:.0f} min")
    wu = (ROOT / "reports" / "warning_utility.md").read_text()
    row = next(line for line in wu.splitlines() if line.startswith("| Demo model"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    print(f"Warned >= 30 min ahead : {cells[5]} of all onsets   (reports/warning_utility.md)")

    rule("App = evaluation (replay parity)")
    p = json.loads((ROOT / "reports" / "serving_parity.json").read_text())
    print(f"{p['compared']:,} saved test forecasts reproduced by the app within {p['tolerance_mg_dl']:g} mg/dL — "
          f"{p['over_tolerance']} over tolerance, outcome {p['outcome'].upper()}   (reports/serving_parity.json)")

    rule("README numbers vs saved artifacts")
    em = (ROOT / "reports" / "evidence_manifest.md").read_text()
    hit = re.search(r"\*\*(\d+ of \d+ claims match[^*]*)\*\*", em)
    print((hit.group(1) if hit else "see reports/evidence_manifest.md") + "   (reports/evidence_manifest.md)")
    print("\nNot clinical validation. Research prototype; synthetic participants are fictional.")


if __name__ == "__main__":
    main()
