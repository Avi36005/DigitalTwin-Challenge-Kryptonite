import type { ResearchSummaryList } from "@/api/types";

/** The /research-summaries payload as this repository's saved summaries produce it (20 Oct 2026). */
export const researchSummaries: ResearchSummaryList = {
  "schema_version": "1.0",
  "items": [
    {
      "decision_id": "D-043",
      "experiment_id": "gt-2h-2026-10-20",
      "evaluated_on": "people_held_out",
      "status": "available",
      "participants": 14,
      "opened_at": "2026-10-20T09:35:52+00:00",
      "reopened_at": [],
      "findings": [
        {
          "key": "forecast_120",
          "verdict": "shown",
          "unit": "mg/dL",
          "values": {
            "mae": 30.617,
            "persistence_mae": 35.869
          },
          "estimate": -5.25,
          "ci95": [
            -6.44,
            -4.05
          ],
          "better_for": 14,
          "n": 14
        },
        {
          "key": "notice_120",
          "verdict": "not_shown",
          "unit": "min",
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
          "unit": "mg/dL",
          "values": {},
          "estimate": -0.86,
          "ci95": [
            -2.6,
            1.02
          ],
          "better_for": 8,
          "n": 14
        }
      ]
    },
    {
      "decision_id": "D-045",
      "experiment_id": "gt-2h-ext-2026-10-20",
      "evaluated_on": "independent_cohort",
      "status": "available",
      "participants": 98,
      "opened_at": "2026-10-20T10:10:25+00:00",
      "reopened_at": [],
      "findings": [
        {
          "key": "forecast_120",
          "verdict": "shown",
          "unit": "mg/dL",
          "values": {
            "mae": 29.553,
            "persistence_mae": 31.675
          },
          "estimate": -2.122,
          "ci95": [
            -2.672,
            -1.526
          ],
          "better_for": 78,
          "n": 98
        }
      ]
    },
    {
      "decision_id": "D-044",
      "experiment_id": "gt-2h-clf-2026-10-20",
      "evaluated_on": "people_held_out",
      "status": "available",
      "participants": null,
      "opened_at": "2026-10-20T09:57:29+00:00",
      "reopened_at": [
        "2026-10-20T09:58:18+00:00"
      ],
      "findings": [
        {
          "key": "classifier",
          "verdict": "negative",
          "unit": null,
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
      "evaluated_on": "reanalysis_inspected",
      "status": "available",
      "participants": 14,
      "opened_at": "2026-10-20T12:24:25+00:00",
      "reopened_at": [],
      "findings": [
        {
          "key": "ranges_120",
          "verdict": "shown",
          "unit": "%",
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
          "unit": "points",
          "values": {
            "early_selected": 126,
            "early_incumbent": 123,
            "onsets": 329,
            "lead_median": 15.0
          },
          "estimate": 0.911854103343465,
          "ci95": [
            -5.484855588897224,
            6.632183908045973
          ],
          "better_for": null,
          "n": 14
        },
        {
          "key": "profile_prior_120",
          "verdict": "not_shown",
          "unit": "mg/dL",
          "values": {
            "first_24h_estimate": -0.9275107449871738,
            "first_24h_ci_low": -2.7386233148081605,
            "first_24h_ci_high": 0.48115064945824476
          },
          "estimate": -0.5320612265160362,
          "ci95": [
            -1.5719932584685548,
            0.5825984668218389
          ],
          "better_for": 10,
          "n": 14
        }
      ]
    }
  ]
};

export const researchSummariesNotRun: ResearchSummaryList = {
  schema_version: "1.0",
  items: researchSummaries.items.map((it) => ({ decision_id: it.decision_id, experiment_id: it.experiment_id, evaluated_on: it.evaluated_on, status: "not_run", reopened_at: [], findings: [] })),
};
