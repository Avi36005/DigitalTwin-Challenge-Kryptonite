import { ArrowRight, Database } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import { featureSetOf, modelUsesProfile } from "@/lib/forecast";
import { fmtPct, modeLabel } from "@/lib/format";
import { paths } from "@/lib/routes";
import { durationLabel, replayTime } from "@/lib/time";
import { RECORDED_UNAVAILABLE, useDeployment } from "@/state/deployment";
import { useDatasets, useEvaluation, useServing } from "@/state/evaluation";
import { snapshotLine } from "@/lib/snapshot";
import { Disclosure } from "@/components/evidence/Disclosure";
import { useLatestForecast, usePatient, usePatients, useReadiness, useSessions, useTwin } from "@/state/replay";
import { EmptyState, InlineNotice, PageHeader, Section, Skeleton, StatusLabel } from "@/components/ui";

export function DataQualityPage() {
  const patients = usePatients();
  const ready = useReadiness();
  const ev = useEvaluation();
  const { publicDemo } = useDeployment();
  const all = useMemo(() => patients.data?.items ?? [], [patients.data]);
  const firstDataset = publicDemo ? undefined : all.find((p) => p.mode === "dataset_replay");
  const firstSynthetic = all.find((p) => p.mode === "synthetic_demo");
  const ds = usePatient(firstDataset?.patient_id);
  const syn = usePatient(firstSynthetic?.patient_id);
  const cohortCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of all.filter((x) => x.mode === "dataset_replay" && !publicDemo)) m.set(p.cohort.label, (m.get(p.cohort.label) ?? 0) + 1);
    return Array.from(m.entries());
  }, [all, publicDemo]);
  const cohort = ev.data?.cohort;
  const servingVersion = (ev.data?.protocol as { model_version?: string } | undefined)?.model_version;
  const servingRequiresProfile = useServing().data?.items.find((x) => x.mode === "dataset_replay")?.requires_complete_profile === true;

  return (
    <>
      <PageHeader title="Data quality">
        What data each replay rests on: the current session’s readings, dataset-level coverage and the limits of the model’s inputs.
      </PageHeader>
      {publicDemo && <InlineNotice tone="neutral" role="note">{RECORDED_UNAVAILABLE} Only the fictional synthetic data is described
        live here; recorded-data quality is documented in the repository’s data card.</InlineNotice>}
      {patients.isLoading ? <Skeleton h={300} /> : all.length === 0 ? (
        <EmptyState icon={Database} title="No data loaded">Import CGMacros or build the synthetic fixtures.</EmptyState>
      ) : (
        <>
          <CurrentReplay />

          <DataSources />

          <Section title="Sources and time policy">
            <dl className="dl dl--wide">
              <dt>Recorded data</dt>
              <dd>{firstDataset ? <>{firstDataset.dataset.name} {firstDataset.dataset.version} · {firstDataset.dataset.license}{firstDataset.dataset.citation_url && <> · <a href={firstDataset.dataset.citation_url} target="_blank" rel="noreferrer">dataset DOI</a></>}</> : publicDemo ? "Not available in this public demonstration (local installation only)" : "Not imported on this machine"}</dd>
              <dt>Synthetic data</dt>
              <dd>{firstSynthetic ? <>{firstSynthetic.dataset.name} · {firstSynthetic.dataset.license}</> : "Not built"}</dd>
              <dt>Cohorts</dt>
              <dd>{cohortCounts.map(([c, n]) => `${c}: ${n}`).join(" · ") || "—"}</dd>
              <dt>Readiness</dt>
              <dd>{ready.data ? <>{ready.data.dataset.detail} {ready.data.model.detail}</> : ready.isError ? "API unreachable" : "—"}</dd>
              <dt>Recorded timeline</dt><dd>{ds.data?.time_policy.description ?? "—"}</dd>
              <dt>Availability</dt>
              <dd>{ds.data ? `${ds.data.availability_policy_id}: sensor readings become available when observed (the study CGM was blinded, so this is a replay approximation); meal logs are shown for context only; baseline labs are available at twin initialisation.` : "—"}</dd>
              <dt>Synthetic timeline</dt><dd>{syn.data?.time_policy.description ?? "—"}</dd>
            </dl>
          </Section>

          <Section title="Model inputs and their limits">
            <ul className="limits">
              <li>Glucose: native Dexcom G6 Pro readings about every 5 minutes, recovered from a 1-minute interpolated table; interpolated rows
                are never counted as measurements. Gaps longer than 15 minutes stay gaps and make forecasts degraded or unavailable.</li>
              <li>Activity: 5-minute wearable summaries (heart rate, METs). Missing coverage is treated as missing, not as inactivity.</li>
              <li>Meals: shown for context only and excluded from the primary model, because when meal logs became available in real time is undocumented.</li>
              <li>
                Baseline profile (age, sex, BMI, HbA1c, fasting glucose, fasting insulin, triglycerides, HDL):{" "}
                {modelUsesProfile(servingVersion) === false
                  ? `not used by the serving model (${featureSetOf(servingVersion)}), which forecasts from recent glucose and activity.`
                  : modelUsesProfile(servingVersion) === true
                    ? `included among the serving model’s inputs (${featureSetOf(servingVersion)}), alongside recent glucose and activity. The values are fixed for each participant’s record${servingRequiresProfile ? "; if any is missing, the model abstains instead of guessing" : ""}.`
                    : "use depends on the loaded model."}
              </li>
              <li>Medication, insulin use and illness were not recorded and cannot be modelled.</li>
            </ul>
          </Section>

          {cohort && (
            <Section title="Evaluation accounting" description="Primary Type 2 cohort; chronological split within each participant">
              <div className="table-scroll">
                <table className="table">
                  <thead><tr><th scope="col">Segment</th><th scope="col" className="num">Forecast times</th><th scope="col" className="num">Covered hours</th><th scope="col" className="num">New high-glucose onsets</th></tr></thead>
                  <tbody>
                    {Object.keys(cohort.origins_by_split).map((k) => (
                      <tr key={k}><th scope="row">{k[0].toUpperCase() + k.slice(1)}</th><td className="num">{cohort.origins_by_split[k].toLocaleString()}</td>
                        <td className="num">{cohort.covered_hours_by_split[k]}</td><td className="num">{cohort.events_by_split[k]}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="helper">{cohort.excluded.length} recorded participants are outside the primary analysis (cohort by the dataset’s HbA1c criterion). Forecast times overlap and are not independent patients.</p>
            </Section>
          )}

          <Section title="Per-participant coverage" description="Native primary-device readings; missing values are shown as missing">
            <div className="table-scroll table-scroll--sticky table-scroll--tall" tabIndex={0} role="region" aria-label="Per-participant coverage table">
              <table className="table">
                <thead>
                  <tr><th scope="col" className="col-sticky">Participant</th><th scope="col">Cohort</th><th scope="col">Device</th><th scope="col" className="num">Days</th>
                    <th scope="col" className="num">Readings</th><th scope="col" className="num">CGM coverage</th><th scope="col" className="num">Gaps &gt;15 min</th>
                    <th scope="col" className="num">Wearable coverage</th><th scope="col" className="num">Meals</th><th scope="col">Missing baseline fields</th><th scope="col">Analysis</th></tr>
                </thead>
                <tbody>
                  {(publicDemo ? all.filter((p) => p.mode === "synthetic_demo") : all).map((p) => (
                    <tr key={p.patient_id}>
                      <th scope="row" className="col-sticky">{p.display_alias}</th>
                      <td className="nowrap">{p.cohort.label}</td>
                      <td className="nowrap">{p.coverage.primary_device ?? "—"}</td>
                      <td className="num">{p.coverage.recording_days?.toFixed(1) ?? "—"}</td>
                      <td className="num">{p.coverage.glucose_samples?.toLocaleString() ?? "—"}</td>
                      <td className="num">{fmtPct(p.coverage.glucose_coverage_fraction, 1)}</td>
                      <td className="num">{p.coverage.gaps_over_threshold ?? "—"}</td>
                      <td className="num">{fmtPct(p.coverage.activity_coverage_fraction, 0)}</td>
                      <td className="num">{p.coverage.meals_logged ?? "—"}</td>
                      <td>{p.missing_fields.length ? p.missing_fields.join(", ") : <span className="muted">None</span>}</td>
                      <td>{p.mode === "synthetic_demo" ? "Synthetic" : p.eligible_for_primary_analysis ? "Primary" : <span className="muted">Exploratory{p.exclusion_reason ? ` — ${p.exclusion_reason}` : ""}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}
    </>
  );
}

/** The most recent replay's data state, so "current session" quality is not confused with dataset-level coverage. */
function CurrentReplay() {
  const sessions = useSessions();
  const s = sessions.data?.items[0];
  const latest = useLatestForecast(s);
  const twin = useTwin(s);
  if (!s) {
    return (
      <Section title="Current replay" divider={false}>
        <p className="muted">No replay session is open. Data quality for a session appears here once you start one.</p>
      </Section>
    );
  }
  const fr = s.freshness;
  const reasons = latest.data?.forecast?.quality.reasons ?? [];
  return (
    <Section title="Current replay" divider={false}
      description={<>{s.patient_alias} · {modeLabel(s.mode)} · replay time {replayTime(s.clock_at)}</>}
      actions={<Link to={paths.session(s.id)} className="text-link">Open replay<ArrowRight size={15} aria-hidden /></Link>}>
      <dl className="dl dl--wide">
        <dt>Latest reading</dt><dd className="num">{fr.latest_glucose_at ? replayTime(fr.latest_glucose_at) : "None released"}</dd>
        <dt>Freshness</dt>
        <dd>{fr.status === "fresh" ? `Fresh · ${durationLabel(fr.latest_glucose_age_minutes)} old`
          : fr.status === "stale" ? <StatusLabel tone="attention">Stale · {durationLabel(fr.latest_glucose_age_minutes)} old (limit {fr.stale_threshold_minutes} min)</StatusLabel>
          : "No data released yet"}</dd>
        <dt>Readings, last 60 min</dt><dd className="num">{twin.data ? `${twin.data.history.valid_samples_60} of ~12 expected at a 5-minute cadence` : "—"}</dd>
        <dt>Forecast inputs</dt>
        <dd>{reasons.length ? reasons.map((r) => r.message).join(" ") : latest.data?.forecast ? "Complete for the latest forecast." : "No forecast issued yet."}</dd>
      </dl>
    </Section>
  );
}

const STATUS: Record<string, string> = {
  eligible_for_experiment: "Imported · eligible",
  imported: "Imported",
  available_locally: "Downloaded, not imported",
  access_required: "Access required",
  planned: "Planned",
  failed_validation: "Failed validation",
};

/** Audited dataset inventory: publisher scale is external metadata; imported, eligible and assessed are measured here. */
function DataSources() {
  const inv = useDatasets();
  const d = inv.data;
  if (inv.isLoading) return <Skeleton h={160} />;
  if (!d || d.status !== "available") {
    return (
      <Section title="Data sources and scale">
        <p className="muted">No audited inventory on this machine. Run <code>glucotwin data manifest</code>.</p>
      </Section>
    );
  }
  const datasets = d.datasets ?? [];
  const blocked = datasets.filter((x) => (x.user_steps ?? []).length);
  const ov = d.overlap_check as { recordings_compared?: number; max_overlap?: number; flagged_pairs?: unknown[] } | null;
  return (
    <Section title="Data sources and scale" description={snapshotLine(d)
      ? `${snapshotLine(d)}; audited ${d.generated_at ? new Date(d.generated_at).toISOString().slice(0, 10) : ""}`
      : `Audited ${d.generated_at ? new Date(d.generated_at).toISOString().slice(0, 10) : ""} from verified local files`}>
      {d.summary_sentence && <p className="lede__sub">{d.summary_sentence}</p>}
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Dataset inventory">
        <table className="table">
          <caption className="visually-hidden">Datasets: publisher-reported scale versus what was imported and used here</caption>
          <thead>
            <tr>
              <th scope="col">Source</th><th scope="col">Status</th>
              <th scope="col" className="num" title="People reported by the publisher; external metadata, not a GlucoTwin count">Publisher-reported</th>
              <th scope="col" className="num" title="People parsed into the canonical layer on this machine">Imported</th><th scope="col">Eligible here</th>
              <th scope="col" className="num" title="Native CGM readings (all devices)">Native readings</th><th scope="col" className="num">Observed hours</th>
              <th scope="col">Cadence · inputs</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((x) => (
              <tr key={x.dataset_id}>
                <th scope="row" className="table__name">{x.name}
                  <span className="table__sub">{[x.release, x.country_site].filter(Boolean).join(" · ")}</span>
                  {x.license && <span className="table__sub">{x.license}</span>}</th>
                <td className="nowrap">{STATUS[x.access_status] ?? x.access_status}</td>
                <td className="num">{x.publisher_participants?.toLocaleString() ?? "—"}</td>
                <td className="num">{x.parsed_participants?.toLocaleString() ?? "—"}</td>
                <td>{Object.entries(x.eligible ?? {}).length
                  ? Object.entries(x.eligible ?? {}).map(([k, v]) => <span key={k} className="eligible-line"><span className="num">{v}</span> {k}</span>)
                  : "—"}</td>
                <td className="num">{x.native_readings?.toLocaleString() ?? "—"}
                  {x.detail && x.access_status !== "access_required" && x.access_status !== "planned" && <span className="table__sub">{x.detail}</span>}</td>
                <td className="num">{x.observed_hours != null ? Math.round(x.observed_hours).toLocaleString() : "—"}</td>
                <td>{x.native_cadence_minutes?.length ? `${x.native_cadence_minutes.join(" / ")} min` : "—"}
                  {x.wearable && <span className="table__sub">Wearable: {x.wearable}</span>}
                  {x.profile && <span className="table__sub">Profile: {x.profile}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="helper">Imported does not mean used for training, and evaluated is split by internal and external regime on Model evidence. Observed hours
        count each native reading for at most one cadence interval, so gaps add nothing. Catalogue totals (for example Glucose-ML) are never GlucoTwin
        counts. {ov && `Overlap check: ${ov.recordings_compared ?? 0} recordings compared, largest overlap ${fmtPct(ov.max_overlap ?? null, 1)}, ${ov.flagged_pairs?.length ?? 0} flagged.`}
        {" "}Synthetic participants are listed separately and never counted as real people.</p>
      {blocked.map((x) => (
        <Disclosure key={x.dataset_id} title={`${x.name}: steps only you can complete`} summary={STATUS[x.access_status]}>
          <ol className="limits">{(x.user_steps ?? []).map((u, i) => <li key={i}>{u}</li>)}</ol>
          <p className="helper">Nothing has been requested, accepted or downloaded on your behalf. Records must stay on this machine and must not be pasted
            into external services or AI tools.</p>
        </Disclosure>
      ))}
    </Section>
  );
}
