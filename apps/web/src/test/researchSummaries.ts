import type { ResearchSummaryList } from "@/api/types";

/** The /research-summaries payload as this repository's saved summaries produce it (20 Oct 2026). */
export const researchSummaries: ResearchSummaryList = {
  "schema_version": "1.0",
  "source": null,
  "snapshot_exported_at": null,
  "snapshot_commit": null,
  "items": [
    {
      "decision_id": "D-043",
      "experiment_id": "gt-2h-2026-10-20",
      "status": "available",
      "status_detail": null,
      "evaluated_on": "people_held_out",
      "participants": 14,
      "opened_at": "2026-10-20T09:35:52+00:00",
      "reopened_at": [],
      "findings": [
        {
          "key": "forecast_120",
          "verdict": "shown",
          "basis": "display_heuristic",
          "basis_note": "Shown when the whole 95 % participant-bootstrap interval of the difference is below zero.",
          "estimate": -5.25,
          "ci95": [
            -6.44,
            -4.05
          ],
          "unit": "mg/dL",
          "better_for": 14,
          "n": 14,
          "values": {
            "mae": 30.617,
            "persistence_mae": 35.869
          }
        },
        {
          "key": "notice_120",
          "verdict": "not_shown",
          "basis": "display_heuristic",
          "basis_note": "Two hours of notice is described as shown only if the median forecast lead reaches 60 minutes; no protocol declared a lead target.",
          "estimate": null,
          "ci95": null,
          "unit": "min",
          "better_for": null,
          "n": null,
          "values": {
            "detected": 315,
            "onsets": 329,
            "false_alarms_per_day": 1.623,
            "lead_median": 15.0,
            "lead_q1": 5.0,
            "lead_q3": 65.0
          }
        },
        {
          "key": "profile_inputs_120",
          "verdict": "not_shown",
          "basis": "display_heuristic",
          "basis_note": "Shown when the whole 95 % interval of with-minus-without profile is below zero.",
          "estimate": -0.86,
          "ci95": [
            -2.6,
            1.02
          ],
          "unit": "mg/dL",
          "better_for": 8,
          "n": 14,
          "values": {}
        }
      ]
    },
    {
      "decision_id": "D-045",
      "experiment_id": "gt-2h-ext-2026-10-20",
      "status": "available",
      "status_detail": null,
      "evaluated_on": "independent_cohort",
      "participants": 98,
      "opened_at": "2026-10-20T10:10:25+00:00",
      "reopened_at": [],
      "findings": [
        {
          "key": "forecast_120",
          "verdict": "shown",
          "basis": "display_heuristic",
          "basis_note": "Shown when the whole 95 % participant-bootstrap interval of the difference is below zero.",
          "estimate": -2.122,
          "ci95": [
            -2.672,
            -1.526
          ],
          "unit": "mg/dL",
          "better_for": 78,
          "n": 98,
          "values": {
            "mae": 29.553,
            "persistence_mae": 31.675
          }
        }
      ]
    },
    {
      "decision_id": "D-044",
      "experiment_id": "gt-2h-clf-2026-10-20",
      "status": "available",
      "status_detail": null,
      "evaluated_on": "people_held_out",
      "participants": null,
      "opened_at": "2026-10-20T09:57:29+00:00",
      "reopened_at": [
        "2026-10-20T09:58:18+00:00"
      ],
      "findings": [
        {
          "key": "classifier",
          "verdict": "negative",
          "basis": "display_heuristic",
          "basis_note": "Described as a negative result because it warned at more than half of eligible times; its report rejects it for warning almost constantly.",
          "estimate": null,
          "ci95": null,
          "unit": null,
          "better_for": null,
          "n": null,
          "values": {
            "detected": 329,
            "onsets": 329,
            "false_alarms_per_day": 0.181,
            "share_time_warning": 0.99,
            "roc_auc": 0.638
          }
        }
      ]
    },
    {
      "decision_id": "D-046",
      "experiment_id": "gt-warn-range-2026-10-20",
      "status": "available",
      "status_detail": null,
      "evaluated_on": "reanalysis_inspected",
      "participants": 14,
      "opened_at": "2026-10-20T12:24:25+00:00",
      "reopened_at": [],
      "findings": [
        {
          "key": "ranges_120",
          "verdict": "shown",
          "basis": "display_heuristic",
          "basis_note": "Described as shown when pooled coverage moved closer to the 80 % target than the incumbent range; D-046 declared pooled calibration as its primary method, not a pass bar.",
          "estimate": null,
          "ci95": null,
          "unit": "%",
          "better_for": null,
          "n": null,
          "values": {
            "before": 0.7648791387365428,
            "after": 0.7981159861872842,
            "before_60": 0.7823679619750714,
            "after_60": 0.7954895962379592,
            "width_before": 88.45097821102597,
            "width_after": 95.10829725583514
          }
        },
        {
          "key": "earlier_warning_120",
          "verdict": "not_shown",
          "basis": "display_heuristic",
          "basis_note": "Shown when the whole 95 % interval of the difference in onsets warned at least 30 minutes ahead is above zero; D-046 part A declared no claim rule.",
          "estimate": 0.911854103343465,
          "ci95": [
            -5.484855588897224,
            6.632183908045973
          ],
          "unit": "points",
          "better_for": null,
          "n": 14,
          "values": {
            "early_selected": 126,
            "early_incumbent": 123,
            "onsets": 329,
            "lead_median": 15.0
          }
        },
        {
          "key": "profile_prior_120",
          "verdict": "not_shown",
          "basis": "declared_rule",
          "basis_note": "D-046 part C declared it before computing: the profile is said to help only if the 95 % interval of profile prior minus population only is below zero at 120 min.",
          "estimate": -0.5320612265160362,
          "ci95": [
            -1.5719932584685548,
            0.5825984668218389
          ],
          "unit": "mg/dL",
          "better_for": 10,
          "n": 14,
          "values": {
            "first_24h_estimate": -0.9275107449871738,
            "first_24h_ci_low": -2.7386233148081605,
            "first_24h_ci_high": 0.48115064945824476
          }
        }
      ]
    }
  ]
};

export const researchSummariesNotRun: ResearchSummaryList = {
  schema_version: "1.0",
  items: researchSummaries.items.map((it) => ({ decision_id: it.decision_id, experiment_id: it.experiment_id, evaluated_on: it.evaluated_on, status: "not_run", reopened_at: [], findings: [] })),
};

/** A summary file that exists but cannot be read, and one written for another experiment. */
export const researchSummariesUnreadable: ResearchSummaryList = {
  schema_version: "1.0",
  items: [
    { decision_id: "D-043", experiment_id: "gt-2h-2026-10-20", evaluated_on: "people_held_out", status: "malformed",
      status_detail: "two_hour_summary.json could not be read as JSON (JSONDecodeError).", reopened_at: [], findings: [] },
    { decision_id: "D-046", experiment_id: "gt-warn-range-2026-10-20", evaluated_on: "reanalysis_inspected", status: "incompatible",
      status_detail: "summary.json belongs to gt-2h-clf-2026-10-20, not gt-warn-range-2026-10-20.", reopened_at: [], findings: [] },
  ],
};
