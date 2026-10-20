import { useEffect, useMemo, useState } from "react";
import { useLocation, useSearchParams } from "react-router";
import type { EvaluationReport, EventMetricsRow } from "@/api/types";
import {
  defaultComparison,
  FAMILY,
  featureLabel,
  fmtLatency,
  LABELS,
  pctLower,
  pipelineName,
  pipelines,
  REGIME,
  roleOf,
  type Pipeline,
} from "@/lib/evidence";
import { fmtNum, fmtPct } from "@/lib/format";
import { snapshotLine } from "@/lib/snapshot";
import { useDeployment } from "@/state/deployment";
import { useEvaluation, useEvaluationById, useEvaluations, useResearch, useResearchSummaries, useServing } from "@/state/evaluation";
import { Disclosure } from "@/components/evidence/Disclosure";
import { ResearchAfterDemo } from "@/components/evidence/ResearchAfterDemo";
import { ResearchEvidence } from "@/components/evidence/ResearchEvidence";
import { SafetyGuardrails } from "@/components/evidence/SafetyGuardrails";
import { EmptyState, InlineNotice, MetadataLine, PageHeader, Section, Skeleton, SortTh } from "@/components/ui";

export function EvidencePage() {
  const { publicDemo } = useDeployment();
  const list = useEvaluations();
  const [params, setParams] = useSearchParams();
  const items = list.data?.items ?? [];
  // default: the evidence behind the serving model; without one (e.g. synthetic-only installs) the latest report,
  // which explains that no recorded-data evaluation has been run — never an unassessed research experiment
  const chosen = params.get("experiment") ?? list.data?.serving_experiment_id ?? null;
  const meta = items.find((x) => x.experiment_id === chosen);
  const research = meta?.regime === "nested_research";
  const latest = useEvaluation();
  const byId = useEvaluationById(research || !chosen ? null : chosen);
  const ev = chosen && !research ? byId : latest;
  const rs = useResearch(research ? chosen : null);
  const summaries = useResearchSummaries(research);
  const r = ev.data;
  const snapshot = snapshotLine(research ? rs.data : r ?? list.data);
  const select = (id: string) => setParams((p) => { const n = new URLSearchParams(p); n.set("experiment", id); return n; }, { replace: true });
  // "#safety-guardrails" (linked from the replay workspace) sits below the results: scroll once they have loaded
  const { hash } = useLocation();
  const loaded = !list.isLoading && !(research ? rs.isLoading : ev.isLoading);
  useEffect(() => {
    if (loaded && hash === "#safety-guardrails") document.getElementById("safety-guardrails")?.scrollIntoView?.();
  }, [loaded, hash]);
  return (
    <>
      <PageHeader title="Model evidence"
        meta={!research && r?.status === "completed" ? (
          <MetadataLine>
            <>Experiment <span className="nowrap">{r.experiment_id}</span></>
            {r.created_at ? `Run ${new Date(r.created_at).toISOString().slice(0, 10)}` : null}
            {r.dataset ? `${r.dataset.name} ${r.dataset.version}` : null}
          </MetadataLine>
        ) : undefined}
        actions={items.length > 1 ? (
          <div className="field-inline">
            <label htmlFor="exp-select">Evidence</label>
            <select id="exp-select" className="select" value={chosen ?? ""} onChange={(e) => select(e.target.value)}>
              {!chosen && <option value="" disabled>Choose evidence</option>}
              {items.map((x) => (
                <option key={x.experiment_id} value={x.experiment_id} disabled={x.status === "not_run"}>
                  {x.title}{x.status === "development_only" ? " (development only)" : x.status === "not_run" ? " (not run)" : ""}
                </option>
              ))}
            </select>
          </div>
        ) : undefined}>
        Forecast error and warnings, read from the saved experiment artifacts: later recordings from participants represented in training (demo model) or people held out entirely (research).
      </PageHeader>
      {publicDemo && (
        <InlineNotice tone="neutral" role="note">
          <strong>Replays in this public demonstration use the synthetic demonstration model</strong>, fitted on fictional data. The
          results on this page are the published evidence for the real-data models, read from saved experiment files, and are
          also reported in the repository’s README and reports. They are not this demonstration’s performance, and nothing here
          was measured on the synthetic replays.
        </InlineNotice>
      )}
      {snapshot && <p className="page-note snapshot-line">{snapshot}.</p>}
      {!publicDemo && <ServingLine selected={chosen} regime={meta ? REGIME[meta.regime] : undefined} />}
      {list.isLoading || (!research && ev.isLoading) || (research && rs.isLoading) ? <Skeleton h={300} /> : research ? (
        rs.isError ? <EmptyState title="Research report unavailable">{(rs.error as Error).message}</EmptyState>
          : rs.data?.status !== "completed" ? <EmptyState title="Research experiment not assessed yet">{rs.data?.status_message}</EmptyState>
            : <ResearchEvidence r={rs.data} />
      ) : ev.isError ? (
        <EmptyState title="Evaluation unavailable">{(ev.error as Error).message}</EmptyState>
      ) : r && r.status !== "completed" ? (
        <EmptyState title={r.status === "not_run" ? "Evaluation not run" : r.status === "synthetic_only" ? "Synthetic-only demonstration" : "Evaluation unavailable"}>
          {r.status_message}
        </EmptyState>
      ) : r ? <Evidence r={r} /> : null}
      {research && !list.isLoading && (
        <ResearchAfterDemo data={summaries.data} loading={summaries.isLoading} error={summaries.error as Error | null} />
      )}
      <SafetyGuardrails />
    </>
  );
}

/** The model replay sessions use, stated on its own so a research report is never mistaken for the serving model. */
function ServingLine({ selected, regime }: { selected: string | null; regime?: string }) {
  const s = useServing();
  const d = s.data?.items.find((x) => x.mode === "dataset_replay");
  if (!d) return null;
  const same = d.experiment_id === selected;
  return (
    <p className="page-note serving-line" aria-live="polite">
      <strong>Serving model:</strong>{" "}
      {d.status === "ready" ? <span className="wrap-id">{d.model_version}</span> : d.detail}
      {d.experiment_id && <> · from {d.experiment_id}</>}
      {selected && <> · showing {same ? "its own evidence" : <>a different experiment{regime ? ` (${regime})` : ""} — its results did not change the serving model</>}</>}
    </p>
  );
}

function Evidence({ r }: { r: EvaluationReport }) {
  const results = useMemo(() => r.forecast_results ?? [], [r.forecast_results]);
  const cohort = r.cohort!;
  const testAll = useMemo(() => pipelines(results.filter((x) => x.split === "test")), [results]);
  const serving = testAll.find((p) => p.selected);
  const persistence = testAll.find((p) => p.family === "persistence");
  const m30 = serving?.h30?.mae_mg_dl.value;
  const m60 = serving?.h60?.mae_mg_dl.value;
  const p30 = persistence?.h30?.mae_mg_dl.value;
  const p60 = persistence?.h60?.mae_mg_dl.value;
  const l30 = pctLower(m30, p30);
  const l60 = pctLower(m60, p60);
  const disclosures = r.selection_disclosures ?? [];
  const ev = servingEvent(r);
  const cov = servingCoverage(r).filter((x) => x.split === "test");

  return (
    <div className="evidence">
      {disclosures.length > 0 ? (
        <InlineNotice tone="attention" role="note">
          <strong>Fusion-constrained result.</strong> {r.status_message}{" "}
          <a href="#disclosures-title" className="text-link">What this does and does not show</a>
        </InlineNotice>
      ) : r.corrects_experiment_id && (
        <InlineNotice tone="attention" role="note">
          <strong>Corrected retrospective result.</strong> This experiment re-runs the declared protocol of{" "}
          <span className="nowrap">{r.corrects_experiment_id}</span> after fixing two code defects (activity-window features and
          warning accounting). Its test segment had already been inspected there, so these are not untouched test results; the
          original results are preserved.
        </InlineNotice>
      )}
      <dl className="facts-row" aria-label="Evaluation context">
        <div><dt>Dataset</dt><dd>{r.dataset?.name} {r.dataset?.version}</dd></div>
        <div><dt>Evaluated participants</dt><dd>{cohort.participants_included} with Type 2 diabetes <span className="muted">of {cohort.participants_in_source} in the dataset</span></dd></div>
        <div><dt>Final-test segment</dt><dd>{(cohort.origins_by_split.test ?? 0).toLocaleString()} forecast times <span className="muted">≈ {Math.round(cohort.covered_hours_by_split.test ?? 0)} h</span></dd></div>
        <div><dt>Serving model</dt><dd>{serving ? `${FAMILY[serving.family] ?? serving.family} · ${serving.feature} · ${serving.pers === "adaptive" ? "adaptive" : serving.pers}` : "—"}</dd></div>
      </dl>

      <Section title="Results at a glance" divider>
        {serving && m30 != null && m60 != null ? (
          <>
            <p className="lede__main">
              {FAMILY[serving.family] ?? serving.family} ({featureLabel(serving.feature)}){" "}
              {serving.pers === "adaptive" ? "with patient adaptation " : ""}is the selected replay model. Final-test results on
              later recordings of the same {cohort.participants_included} participants, not new patients:
            </p>
            <dl className="glance" aria-label="Final-test results of the serving pipeline">
              {([[30, m30, p30, l30], [60, m60, p60, l60]] as const).map(([h, m, p, l]) => (
                <div key={h}>
                  <dt>{h}-min error (MAE)</dt>
                  <dd className="glance__value num">{m.toFixed(2)}<span className="glance__unit">mg/dL</span></dd>
                  {p != null && <dd className="glance__sub">Persistence <span className="num">{p.toFixed(2)}</span>{l != null && <> · {l.toFixed(1)}% lower</>}</dd>}
                </div>
              ))}
              {ev && (
                <div>
                  <dt>High-glucose onsets warned</dt>
                  <dd className="glance__value num">{ev.detected_onsets}<span className="glance__unit">of {ev.true_onsets}</span></dd>
                  {ev.qualified_lead_minutes_median?.value != null && <dd className="glance__sub">Median forecast lead {ev.qualified_lead_minutes_median.value} min</dd>}
                </div>
              )}
              {ev && (
                <div>
                  <dt>False alarms</dt>
                  <dd className="glance__value num">{ev.false_alarm_episodes}<span className="glance__unit">of {ev.warning_episodes} warnings</span></dd>
                  <dd className="glance__sub">
                    {ev.false_alarms_per_observed_patient_day?.value != null
                      ? <><span className="num">{ev.false_alarms_per_observed_patient_day.value.toFixed(2)}</span> per observed participant-day</>
                      : <><span className="num">{fmtNum(ev.false_alarms_per_patient_day.value, 2)}</span> per eligible participant-day</>}
                  </dd>
                </div>
              )}
              {cov.length > 0 && (
                <div>
                  <dt>Prediction-range coverage</dt>
                  <dd className="glance__value num">{cov.map((x) => fmtPct(x.empirical_coverage.value, 1)).join(" / ")}</dd>
                  <dd className="glance__sub">Target {Math.round(cov[0].interval_level * 100)}% · {cov.map((x) => `${x.horizon_minutes}`).join(" / ")} min</dd>
                </div>
              )}
            </dl>
            <p className="helper">{LABELS.maeHelp} Mean absolute error is in mg/dL; it is not an accuracy percentage. Details, intervals
              and per-participant results are below.</p>
          </>
        ) : <p className="muted">No serving pipeline is recorded in this report.</p>}
      </Section>

      {disclosures.length > 0 && (
        <Section title="What this result does and does not show" id="disclosures">
          <ul className="limits">{disclosures.map((d, i) => <li key={i}>{d}</li>)}</ul>
        </Section>
      )}

      <Comparison r={r} />

      <div className="disclosures">
        <PairedDifferences r={r} />
        <RangeCoverage r={r} />
        <Warnings r={r} />
        <PerParticipant r={r} serving={serving} />
        <Secondary r={r} />
        <Protocol r={r} />
      </div>

      <Limitations items={r.limitations ?? []} />
    </div>
  );
}

/* ---------------------------------------------------------------- comparison */
type SortKey = "rule" | "name" | "mae30" | "mae60" | "rmse30" | "rmse60" | "role";

function Comparison({ r }: { r: EvaluationReport }) {
  const [split, setSplit] = useState<"test" | "validation">("test");
  const [all, setAll] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "rule", dir: 1 }); // serving first, then baselines
  const groups = useMemo(() => pipelines((r.forecast_results ?? []).filter((x) => x.split === split)), [r, split]);
  const serving = groups.find((p) => p.selected);
  const shown = useMemo(() => {
    const base = all ? [...groups].sort((a, b) => Number(b.selected) - Number(a.selected) || (a.h60?.mae_mg_dl.value ?? Infinity) - (b.h60?.mae_mg_dl.value ?? Infinity)) : defaultComparison(groups);
    if (sort.key === "rule") return base;
    const v = (p: Pipeline): number | string => {
      switch (sort.key) {
        case "name": return pipelineName(p);
        case "role": return roleOf(p, serving);
        case "mae30": return p.h30?.mae_mg_dl.value ?? Infinity;
        case "mae60": return p.h60?.mae_mg_dl.value ?? Infinity;
        case "rmse30": return p.h30?.rmse_mg_dl.value ?? Infinity;
        case "rmse60": return p.h60?.rmse_mg_dl.value ?? Infinity;
        default: return 0;
      }
    };
    return [...base].sort((a, b) => (v(a) < v(b) ? -1 : v(a) > v(b) ? 1 : 0) * sort.dir);
  }, [groups, all, sort, serving]);
  const onSort = (k: SortKey) => setSort((s) => ({ key: k, dir: s.key === k ? (s.dir === 1 ? -1 : 1) : 1 }));
  const better = serving ? groups.filter((p) => !p.selected && (p.h60?.mae_mg_dl.value ?? Infinity) < (serving.h60?.mae_mg_dl.value ?? -Infinity)).length : 0;
  const sel = r.selection;

  return (
    <Section title="Comparison" description={`${LABELS.mae}, mg/dL. Lower is better.`}
      actions={
        <div className="tabs" role="tablist" aria-label="Evaluation split">
          {(["test", "validation"] as const).map((s) => (
            <button key={s} role="tab" type="button" aria-selected={split === s} onClick={() => setSplit(s)}>
              {s === "test" ? "Final test" : "Validation (selection)"}
            </button>
          ))}
        </div>
      }>
      <p className="table-caption">
        {all ? `All ${groups.length} configurations.` : "Selected comparison: the serving pipeline, the baselines and the closest comparable candidate."}
        {!all && better > 0 && split === "test" && ` ${better} other configuration${better === 1 ? " has" : "s have"} lower 60-minute test error — see all configurations.`}
        {" "}<button type="button" className="text-btn" aria-expanded={all} onClick={() => setAll((x) => !x)}>
          {all ? "Show selected comparison" : "Show all configurations"}
        </button>
      </p>
      <div className={`table-scroll${all ? " table-scroll--sticky" : ""}`} tabIndex={0} role="region" aria-label="Model comparison table">
        <table className="table">
          <caption className="visually-hidden">{split === "test" ? "Final test" : "Validation-selection"} mean absolute error by model configuration</caption>
          <thead>
            <tr>
              <SortTh k="name" label="Model / configuration" sort={sort} onSort={onSort} />
              <SortTh k="mae30" label="MAE 30 min" sort={sort} onSort={onSort} num />
              <SortTh k="mae60" label="MAE 60 min" sort={sort} onSort={onSort} num />
              {all && <SortTh k="rmse30" label="RMSE 30 min" sort={sort} onSort={onSort} num />}
              {all && <SortTh k="rmse60" label="RMSE 60 min" sort={sort} onSort={onSort} num />}
              {all && <th scope="col" className="num">Participants</th>}
              {all && <th scope="col" className="num" title={LABELS.availabilityHelp}>{LABELS.availability}</th>}
              {all && <th scope="col" className="num" title={LABELS.latencyHelp}>Inference / 1,000</th>}
              <SortTh k="role" label="Role" sort={sort} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {shown.map((p) => (
              <tr key={p.key} className={p.selected ? "row-serving" : undefined}>
                <th scope="row" className="table__name">
                  {pipelineName(p)}
                  <span className="table__sub">{p.label}</span>
                </th>
                <td className="num">{fmtNum(p.h30?.mae_mg_dl.value, 2)}</td>
                <td className="num">{fmtNum(p.h60?.mae_mg_dl.value, 2)}</td>
                {all && <td className="num">{fmtNum(p.h30?.rmse_mg_dl.value, 2)}</td>}
                {all && <td className="num">{fmtNum(p.h60?.rmse_mg_dl.value, 2)}</td>}
                {all && <td className="num">{p.h60?.n_patients ?? "—"}</td>}
                {all && <td className="num">{fmtPct(p.h60?.coverage_fraction, 1)}</td>}
                {all && <td className="num">{fmtLatency(p.h60?.inference_ms_per_1k)}</td>}
                <td>{p.selected ? <span className="serving-mark">Serving pipeline</span> : roleOf(p, serving)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {all && (
        <p className="helper">
          {LABELS.availability}: {LABELS.availabilityHelp} {LABELS.latency}: {LABELS.latencyHelp}
        </p>
      )}
      <p className="helper">
        The serving pipeline was chosen on the validation-selection segment, not on this test: {sel?.rule} {sel?.tie_break}{" "}
        {sel?.rationale} The lowest test error therefore does not decide the serving configuration.
      </p>
    </Section>
  );
}

/** The serving pipeline's warning row and prediction-range rows (shared by the glance row and the disclosures). */
function servingEvent(r: EvaluationReport): EventMetricsRow | undefined {
  const rows = (r.event_results ?? []).filter((e) => e.split === "test");
  const sel = (r.forecast_results ?? []).find((x) => x.selected_for_serving);
  if (!sel || !rows.length) return undefined;
  const H = Math.max(...rows.map((e) => e.horizon_minutes));
  return rows.find((e) => e.horizon_minutes === H && e.model_label === `${sel.model_label} (${sel.personalization === "adaptive" ? "adaptive" : "population"})`);
}

function servingCoverage(r: EvaluationReport) {
  const sel = (r.forecast_results ?? []).find((x) => x.selected_for_serving);
  const label = sel ? `${sel.model_label} (${sel.personalization})` : "";
  return (r.interval_results ?? []).filter((x) => x.model_label === label);
}

/* ---------------------------------------------------------------- disclosures */
type Paired = { comparison: string; horizon: number; mean_diff_mae: number; ci95: [number, number]; n_patients: number };

function PairedDifferences({ r }: { r: EvaluationReport }) {
  const paired = (r.optional_experiments ?? []).find((o) => String(o.name).startsWith("Paired"));
  if (!paired || !Array.isArray(paired.results)) return null;
  const rows = paired.results as Paired[];
  return (
    <Disclosure title="Uncertainty across participants" summary="Paired differences with participant-cluster 95% intervals">
      <div className="table-scroll">
        <table className="table">
          <thead><tr><th scope="col">Comparison (final test)</th><th scope="col" className="num">Horizon</th><th scope="col" className="num">Mean MAE difference</th>
            <th scope="col" className="num">95% interval</th><th scope="col" className="num">Participants</th></tr></thead>
          <tbody>
            {rows.map((c, i) => (
              <tr key={i}>
                <td>{c.comparison}</td><td className="num">{c.horizon} min</td>
                <td className="num">{c.mean_diff_mae >= 0 ? "+" : "−"}{Math.abs(c.mean_diff_mae).toFixed(2)} mg/dL</td>
                <td className="num">{c.ci95[0].toFixed(2)} to {c.ci95[1].toFixed(2)}</td>
                <td className="num">{c.n_patients}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="helper">Negative means the first pipeline had lower error. Intervals resample participants, because overlapping
        forecast times from one person are not independent. Rows without an interval in the report show none.</p>
    </Disclosure>
  );
}

function RangeCoverage({ r }: { r: EvaluationReport }) {
  const proto = r.protocol as { intervals?: { level?: number; method?: string } };
  const rows = servingCoverage(r);
  const target = proto.intervals?.level ?? rows[0]?.interval_level ?? 0.8;
  const test = rows.filter((x) => x.split === "test");
  return (
    <Disclosure title="Prediction ranges" summary={test.length ? `Target coverage ${Math.round(target * 100)}% · measured on test ${test.map((t) => fmtPct(t.empirical_coverage.value, 1)).join(" / ")}` : undefined}>
      <div className="table-scroll">
        <table className="table">
          <thead><tr><th scope="col">Segment</th><th scope="col" className="num">Horizon</th><th scope="col" className="num">Target coverage</th>
            <th scope="col" className="num">{LABELS.rangeCoverage}</th><th scope="col" className="num">Mean width</th><th scope="col" className="num">Per-participant coverage</th>
            <th scope="col" className="num">Forecast times</th></tr></thead>
          <tbody>
            {rows.map((x, i) => (
              <tr key={i}>
                <td>{x.split === "test" ? "Final test" : "Calibration"}</td><td className="num">{x.horizon_minutes} min</td>
                <td className="num">{Math.round(x.interval_level * 100)}%</td>
                <td className="num">{fmtPct(x.empirical_coverage.value, 1)}</td>
                <td className="num">{fmtNum(x.mean_width_mg_dl.value, 0)} mg/dL</td>
                <td className="num">{fmtPct(x.per_patient_coverage_min, 0)}–{fmtPct(x.per_patient_coverage_max, 0)}</td>
                <td className="num">{x.n_origins.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="helper">{LABELS.rangeCoverage}: the share of observed targets that fell inside the range. The range is set for a
        target coverage of {Math.round(target * 100)}% on the calibration segment ({proto.intervals?.method ?? "split conformal"}); the
        measured test coverage is evidence about that range, not a new nominal level. Coverage varies by participant; no guarantee.</p>
    </Disclosure>
  );
}

function Warnings({ r }: { r: EvaluationReport }) {
  const rows = (r.event_results ?? []).filter((e) => e.split === "test");
  if (!rows.length) return null;
  const days = rows[0].eligible_patient_days;
  const observed = rows[0].observed_patient_days;
  const corrected = rows.some((e) => e.qualified_lead_minutes_median != null);
  const H = Math.max(...rows.map((e) => e.horizon_minutes));
  const srv = servingEvent(r);
  const lead = (v: { value: number | null } | null | undefined) => (v?.value != null ? `${v.value} min` : "—");
  return (
    <Disclosure title="Research warnings"
      summary={srv ? `Serving rule on test: ${srv.detected_onsets} of ${srv.true_onsets} onsets, ${srv.warning_episodes} warnings, ${srv.false_alarm_episodes} false alarms` : "New high-glucose episodes, final test"}>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr><th scope="col">Rule</th><th scope="col" className="num">Horizon</th><th scope="col" className="num">Margin threshold</th>
              <th scope="col" className="num">Onsets</th><th scope="col" className="num">Detected</th><th scope="col" className="num">Warnings</th>
              <th scope="col" className="num">False alarms</th><th scope="col" className="num">Recall</th><th scope="col" className="num">Precision</th>
              <th scope="col" className="num">{LABELS.falseAlarmRate}</th><th scope="col" className="num">{LABELS.warningRate}</th>
              {corrected && <th scope="col" className="num">{LABELS.falseAlarmRateObserved}</th>}
              {corrected && <th scope="col" className="num" title={LABELS.qualifiedLeadHelp}>{LABELS.qualifiedLead}</th>}
              <th scope="col" className="num">{LABELS.episodeLead}</th>
              {corrected && <th scope="col" className="num">Episodes starting &gt; horizon before onset</th>}
              <th scope="col" className="num">PR-AUC</th></tr>
          </thead>
          <tbody>
            {rows.map((e: EventMetricsRow, i) => (
              <tr key={i} className={srv === e ? "row-serving" : undefined}>
                <td>{e.model_label}</td><td className="num">{e.horizon_minutes} min</td>
                <td className="num">{e.threshold != null ? `${e.threshold >= 0 ? "+" : "−"}${Math.abs(e.threshold)} mg/dL` : "—"}</td>
                <td className="num">{e.true_onsets}</td><td className="num">{e.detected_onsets}</td>
                <td className="num">{e.warning_episodes}</td><td className="num">{e.false_alarm_episodes}</td>
                <td className="num">{fmtNum(e.recall.value, 2)}</td><td className="num">{fmtNum(e.precision.value, 2)}</td>
                <td className="num">{fmtNum(e.false_alarms_per_patient_day.value, 2)}</td>
                <td className="num">{fmtNum(e.warnings_per_patient_day.value, 2)}</td>
                {corrected && <td className="num">{fmtNum(e.false_alarms_per_observed_patient_day?.value, 2)}</td>}
                {corrected && <td className="num">{lead(e.qualified_lead_minutes_median)}</td>}
                <td className="num">{lead(e.lead_time_minutes_median)}</td>
                {corrected && <td className="num">{e.episode_start_lead_over_horizon ?? "—"}</td>}
                <td className="num">{fmtNum(e.origin_pr_auc.value, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="helper">
        A warning fires when the forecast margin (highest forecast minus 180 mg/dL) reaches the threshold chosen on validation
        by event-level F1; it is not a probability. Time bases are approximate (forecast-issued origins × 5-minute cadence):
        eligible, forecastable, uncensored time is {days.toFixed(1)} participant-days on test
        {observed != null ? <>, all observed forecastable time {observed.toFixed(1)} participant-days</> : null}.
        {corrected ? " Compare rates on the same base, or the raw counts." : " The two rates use different bases — compare raw counts, not the rates."}{" "}
        Episode-start-to-onset is measured from the first warning of a merged episode and can exceed the {H}-minute horizon;
        {corrected ? ` the qualified lead (${LABELS.qualifiedLeadHelp.toLowerCase().replace(/\.$/, "")}) is the forecasting lead.` : " it is not a forecasting lead."}
      </p>
    </Disclosure>
  );
}

type PP = { participant: string; label: string; personalization: string; horizon: number; mae: number };

function PerParticipant({ r, serving }: { r: EvaluationReport; serving?: Pipeline }) {
  const pp = (r.per_patient ?? []) as PP[];
  if (!serving || !pp.length) return null;
  const get = (who: string, label: string, pers: string, h: number) => pp.find((x) => x.participant === who && x.label === label && x.personalization === pers && x.horizon === h)?.mae;
  const people = Array.from(new Set(pp.map((x) => x.participant))).sort();
  const base = "persistence:cgm-only-v1";
  const rows = people.map((who) => ({
    who,
    s30: get(who, serving.label, serving.pers, 30), b30: get(who, base, "off", 30),
    s60: get(who, serving.label, serving.pers, 60), b60: get(who, base, "off", 60),
  }));
  const better60 = rows.filter((x) => x.s60 != null && x.b60 != null && x.s60 < x.b60).length;
  return (
    <Disclosure title="Per-participant variation" summary={`Serving pipeline lower than persistence at 60 min for ${better60} of ${rows.length} participants`}>
      <div className="table-scroll">
        <table className="table">
          <thead><tr><th scope="col">Participant</th><th scope="col" className="num">Serving 30 min</th><th scope="col" className="num">Persistence 30 min</th>
            <th scope="col" className="num">Serving 60 min</th><th scope="col" className="num">Persistence 60 min</th></tr></thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.who}><th scope="row">{x.who}</th><td className="num">{fmtNum(x.s30, 2)}</td><td className="num">{fmtNum(x.b30, 2)}</td>
                <td className="num">{fmtNum(x.s60, 2)}</td><td className="num">{fmtNum(x.b60, 2)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="helper">Final-test mean absolute error per participant, mg/dL. A returning participant’s error, not a new person’s.</p>
    </Disclosure>
  );
}

type LopoRow = { horizon: number; lopo_population_mae: number; lopo_adaptive_mae: number };

function Secondary({ r }: { r: EvaluationReport }) {
  const opt = r.optional_experiments ?? [];
  const lopo = opt.find((o) => String(o.name).startsWith("Leave-one"));
  const meal = opt.find((o) => String(o.name).startsWith("Optimistic"));
  const chronos = opt.find((o) => String(o.name).startsWith("Chronos"));
  const lopoBy = lopo && Array.isArray(lopo.results)
    ? [30, 60].map((h) => {
        const rs = (lopo.results as LopoRow[]).filter((x) => x.horizon === h);
        const mean = (k: keyof LopoRow) => rs.reduce((s, x) => s + (x[k] as number), 0) / Math.max(1, rs.length);
        return { h, pop: mean("lopo_population_mae"), ad: mean("lopo_adaptive_mae"), n: rs.length };
      })
    : null;
  return (
    <Disclosure title="Secondary analyses" summary="New-participant cold start, meal-logging sensitivity, optional tracks">
      <dl className="dl">
        {lopoBy && (
          <>
            <dt>New participant (leave one out)</dt>
            <dd>
              {lopoBy.map((b) => `${b.h} min: ${b.pop.toFixed(2)} without and ${b.ad.toFixed(2)} mg/dL with adaptation`).join("; ")} ({lopoBy[0].n} participants).
              <span className="muted"> Secondary: hyperparameters were selected once on all training participants and reused, so this is not a fully nested estimate for new patients.</span>
            </dd>
          </>
        )}
        {meal && Array.isArray(meal.results) && (
          <>
            <dt>Optimistic meal logging</dt>
            <dd>
              {(meal.results as { split: string; horizon: number; mae: number; serving_population_mae: number }[])
                .filter((m) => m.split === "test").map((m) => `${m.horizon} min: ${m.mae.toFixed(2)} vs ${m.serving_population_mae.toFixed(2)} mg/dL without meals`).join("; ") || "Validation only."}
              <span className="muted"> Sensitivity analysis; assumes macronutrients were known at the photo time. Not eligible for serving.</span>
            </dd>
          </>
        )}
        <dt>Chronos-Bolt (optional track)</dt>
        <dd>Not run.{chronos?.detail ? <span className="muted"> {String(chronos.detail)}</span> : null}</dd>
      </dl>
    </Disclosure>
  );
}

function Protocol({ r }: { r: EvaluationReport }) {
  const proto = r.protocol as Record<string, unknown>;
  const ev = proto.event_definition as Record<string, unknown> | undefined;
  return (
    <Disclosure title="Protocol">
      <dl className="dl">
        <dt>Horizons</dt><dd>{(proto.horizons_minutes as number[])?.join(" and ")} minutes</dd>
        <dt>Split</dt><dd>{String(proto.split)} — {Object.entries((proto.split_fractions as Record<string, number>) ?? {}).map(([k, v]) => `${k.replace("_", " ")} ${Math.round(v * 100)}%`).join(", ")}; purge {String(proto.purge_minutes)} min</dd>
        <dt>Device</dt><dd>{String(proto.primary_device)} — native 5-minute readings; interpolated 1-minute rows are not independent measurements</dd>
        <dt>Event</dt><dd>New onset of glucose &gt; {String(ev?.threshold_mg_dl)} mg/dL sustained ≥ {String(ev?.confirm_minutes)} minutes (research definition)</dd>
        <dt>Adaptation</dt><dd>{String(proto.adaptation)}</dd>
        <dt>Warning score</dt><dd>{String(proto.alert_score)}</dd>
        <dt>Model version</dt><dd className="wrap-id">{String(proto.model_version)}</dd>
      </dl>
    </Disclosure>
  );
}

function Limitations({ items }: { items: string[] }) {
  const [all, setAll] = useState(false);
  if (!items.length) return null;
  const head = items.slice(0, 4);
  return (
    <Section title="Limitations">
      <InlineNotice tone="neutral" role="note">
        A retrospective replay of {items[0]?.match(/\d+ participants/)?.[0] ?? "a small cohort"} from a US dataset; nothing here establishes
        clinical performance or performance for patients in India.
      </InlineNotice>
      <ul className="limits">
        {(all ? items : head).map((l, i) => <li key={i}>{l}</li>)}
      </ul>
      {items.length > head.length && (
        <button type="button" className="text-btn" aria-expanded={all} onClick={() => setAll((x) => !x)}>
          {all ? "Show fewer" : `Show all ${items.length} limitations`}
        </button>
      )}
    </Section>
  );
}
