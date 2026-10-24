# Research workbook check

Checked 2026-10-24T08:15:02+00:00 at repository HEAD `8c75de7` (working tree may differ). Workbook `docs/submission/GlucoTwin_Research_Workbook.xlsx` sha256 `ed2b8bfcded3ef5fe81759b679b7d8667a09c3dbc18f73a312d2c84bed25e3db`. Engine: LibreOffice headless (xlsx → xlsx recalculation) + openpyxl read.

**27 passed, 0 failed.**

| Check | Result | Detail |
|---|---|---|
| LibreOffice recalculation produced a workbook | pass | "engine: LibreOffice headless (soffice); 922 formulas" |
| no formula errors after recalculation | pass | [] |
| no MISMATCH / DIFFERS in-sheet checks | pass | [] |
| every formula has a cached value after recalculation | pass | [] |
| Sources SHA-256 match the files on disk | pass | "25 files re-hashed" |
| missing source files shown as 'unavailable' | pass | "none missing on this installation" |
| no missing source rendered as 0 | pass | [] |
| D-053 high-target worsening unrounded ≈ +1.0658 (from artifact) | pass | {"workbook": 1.06583831481999, "artifact": 1.0658383148199846, "limit": 1} |
| D-053 high-target criterion FAIL vs +1.0 limit | pass | "FAIL" |
| D-053 overall and primary gate FAILED; saved flags agree | pass | {"overall": "FAILED", "primary": "FAILED", "saved_primary": "FALSE"} |
| D-053 recorded as not adopted | pass | "NOT ADOPTED (primary gate failed)" |
| no study gate D-048…D-053 shows PASSED (none adopted) | pass | {"D-048": "FAILED", "D-049": "FAILED", "D-050": "FAILED", "D-051": "FAILED", "D-052": "FAILED", "D-053": "FAILED"} |
| false alarms per observed day = saved count / saved observed patient-days (event metadata) | pass | {"value": 1.49222797927461, "numerator": 40, "denominator": 26.8055555555556, "saved": 1.49222797927461} |
| eligible patient-day base kept separate from observed | pass | {"eligible": 17.5069444444444, "observed": 26.8055555555556} |
| 48.4 % uses all onsets (31/64); median lead uses detected onsets (61) | pass | {"share": {"share": 0.484375, "num": 31, "den": 64}, "median": {"median": 30, "den": 61}} |
| ClaimIndex COUNTIF status counts equal the rows and the JSON export | pass | {"countif": {"supported": 200, "supported-arithmetic": 1, "tested": 24, "implemented": 8, "negative-result": 25, "author-reported": 7, "proposed/illustrative": 5, "pending": 3, "unsupported/contradicted": 0, "total": 273}, "rows": {"supported": 200, "supported-arithmetic": 1, "tested": 24, "implemented": 8, "negative-result": 25, "author-reported": 7, "proposed/illustrative": 5, "pending": 3, "uns |
| every claim uses the declared status vocabulary | pass | [] |
| ClaimIndex checks: no MISMATCH | pass | {"matches": 215, "pending": 0} |
| all 23 evidence-manifest groups are in ClaimIndex | pass | {"groups": 23, "missing": []} |
| each manifest check label is mapped (first number of multi-number labels) | pass | {"checks": 97, "mapped_label_rows": 97, "covered_by_split_rows": []} |
| at least two native charts with sheet-range series | pass | {"xl/charts/chart1.xml": ["'Forecasts'!B40", "'Forecasts'!$A$41:$A$42", "'Forecasts'!$B$41:$B$42", "'Forecasts'!C40", "'Forecasts'!$A$41:$A$42", "'Forecasts'!$C$41:$C$42"], "xl/charts/chart2.xml": ["'WarningRanges'!B62", "'WarningRanges'!$A$63:$A$73", "'WarningRanges'!$B$63:$B$73", "'WarningRanges'!C62", "'WarningRanges'!$A$63:$A$73", "'WarningRanges'!$C$63:$C$73"]} |
| autofilter and frozen header on every data sheet | pass | {"filters": {"ClaimIndex": "A15:M288", "Sources": "A4:K524", "Cohorts": "A4:N12", "Forecasts": "A4:N36", "WarningRanges": "A4:J58", "Studies": "A4:S17", "Gates": "A4:K43", "Verification": "A4:Q56", "Guardrails": "A4:G20"}, "freeze": {"ClaimIndex": "C16", "Sources": "B5", "Cohorts": "B5", "Forecasts": "B5", "WarningRanges": "B5", "Studies": "B5", "Gates": "B5", "Verification": "B5", "Guardrails": " |
| internal hyperlinks resolve to sheets | pass | {"links": 18, "bad": []} |
| ClaimIndex is the first sheet | pass | ["ClaimIndex", "Sources", "Cohorts", "Forecasts", "WarningRanges", "Studies", "Gates", "Verification", "Guardrails", "About"] |
| no home paths, e-mail addresses or participant identifiers (xlsx + JSON) | pass | [] |
| perturbation: dependent formulas follow source cells; 'unavailable' propagates as text, not 0 | pass | {"changed": {"cs.pg.high_worsening_60": 0.99, "fus.serv.mae30": 13.5, "fus.ev.false_alarm_episodes": "unavailable"}, "before": {"gate_hi": "FAIL", "primary": "FAILED", "forecast_diff_30": -1.88031245229031, "c_fc01": "matches", "fa_rate": 1.49222797927461}, "after": {"gate_hi": "PASS", "primary": "PASSED", "forecast_diff_30": -1.33660093847569, "c_fc01": "MISMATCH", "c5311_value": 0.99, "fa_rate": |
| delivered workbook untouched by the checks | pass | "ed2b8bfcded3ef5fe81759b679b7d8667a09c3dbc18f73a312d2c84bed25e3db" |

Regenerate: `uv run --group docs python scripts/check_research_workbook.py`. The delivered workbook is never modified; recalculation and the perturbation test run on copies in a temporary directory.
