import { Fragment, useMemo, useState } from "react";
import type { ResearchComparison, ResearchPipeline, ResearchReport, ResearchTrack } from "@/api/types";
import { fmtLatency, fmtSigned, LABELS, POLICY, RESEARCH_LABELS, researchDefault, selectionSummary } from "@/lib/evidence";
import { fmtNum, fmtPct } from "@/lib/format";
import { InlineNotice, MetadataLine, Section } from "@/components/ui";
import { Disclosure } from "./Disclosure";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const TRACKS = [
  { key: "multimodal_5min", tab: "5-minute · CGMacros", note: "Glucose, wearable activity and baseline profile; native Dexcom readings." },
  { key: "portable_15min", tab: "15-minute · portable", note: "CGM only at a 15-minute cadence; the track used for the external cohort." },
] as const;

/** Evidence for the nested participant-level experiment. Every value comes from the saved research report. */
export function ResearchEvidence({ r }: { r: ResearchReport }) {
  const [track, setTrack] = useState<(typeof TRACKS)[number]["key"]>("multimodal_5min");
  const t = r.tracks?.[track];
  const ext = r.external;
  const internalPeople = r.tracks?.multimodal_5min?.participants;
  const cand = (r.candidates ?? {}) as Record<string, Dict>;
  return (
    <div className="evidence">
      <InlineNotice tone="attention" role="note">
        <strong>New-participant research evidence.</strong> Every person in these results was held out from training, tuning and
        calibration. CGMacros was already inspected in v1/v2, so its nested folds are internal validation, not untouched evidence;
        ShanghaiT2DM is the independent cohort. The serving model was not changed by this experiment.
      </InlineNotice>
      <dl className="facts-row" aria-label="Research experiment context">
        <div><dt>Internal assessment</dt><dd>{internalPeople ?? "—"} CGMacros people <span className="muted">5 outer participant folds, each person once</span></dd></div>
        <div><dt>External assessment</dt><dd>{ext?.status === "completed" ? <>{ext.participants} ShanghaiT2DM people <span className="muted">separate 15-minute LightGBM, opened once</span></> : <>Not run <span className="muted">{ext?.reason ?? ""}</span></>}</dd></div>
        <div><dt>Protocol</dt><dd>Frozen {r.frozen_at?.slice(0, 10) ?? "—"} <span className="muted nowrap">hash {r.protocol_hash}</span></dd></div>
        <div><dt>Deployment candidate</dt><dd>{cand.multimodal_5min ? "Frozen, not promoted" : "—"} <span className="muted">not serving</span></dd></div>
      </dl>

      <Section title="Results on held-out people" divider
        actions={
          <div className="tabs" role="tablist" aria-label="Research track">
            {TRACKS.map((x) => (
              <button key={x.key} role="tab" type="button" aria-selected={track === x.key} onClick={() => setTrack(x.key)}>{x.tab}</button>
            ))}
          </div>
        }>
        {t ? <TrackResults t={t} note={TRACKS.find((x) => x.key === track)!.note} /> : <p className="muted">This track has no assessed results.</p>}
      </Section>

      <div className="disclosures">
        {t && <Paired rows={t.comparisons} title="Uncertainty across participants" />}
        {t && <Ranges t={t} />}
        {t?.warnings && <WarningsTable w={t.warnings as Dict} />}
        {t && <ColdStart t={t} />}
        {t && <Selection t={t} />}
        <External r={r} />
        <Handoff cand={cand} />
        <ProtocolNotes r={r} />
      </div>

      <Section title="Limitations">
        <ul className="limits">{(r.limitations ?? []).map((l, i) => <li key={i}>{l}</li>)}</ul>
      </Section>
    </div>
  );
}

function TrackResults({ t, note }: { t: ResearchTrack; note: string }) {
  const [all, setAll] = useState(false);
  const rows = useMemo(() => (all ? t.pipelines : researchDefault(t.pipelines)), [all, t.pipelines]);
  const sel = t.pipelines.find((p) => p.pipeline === "selected" && p.mode === "final");
  const per = t.pipelines.find((p) => p.pipeline === "persistence:-" && p.mode === "off");
  const v2 = t.pipelines.find((p) => p.pipeline === "v2_recipe:dyn-v2" && p.mode === "v2_policy");
  const choice = selectionSummary(t.selection_by_fold as Record<string, { selected?: string }>);
  return (
    <>
      <p className="section__desc">{note} {t.participants} people, each assessed once in its outer fold.</p>
      {sel && (
        <div className="lede">
          <p className="lede__main">
            The declared rule’s choice reached a mean absolute error of <strong className="num">{fmtNum(sel.horizons["30"]?.mae, 2)} mg/dL</strong> at
            30 minutes and <strong className="num">{fmtNum(sel.horizons["60"]?.mae, 2)} mg/dL</strong> at 60 minutes on people it never saw.
          </p>
          <p className="lede__sub">
            Persistence: {fmtNum(per?.horizons["30"]?.mae, 2)} / {fmtNum(per?.horizons["60"]?.mae, 2)} mg/dL
            {v2 && <> · current v2 recipe refit per fold: {fmtNum(v2.horizons["30"]?.mae, 2)} / {fmtNum(v2.horizons["60"]?.mae, 2)} mg/dL</>}.
            Chosen per fold: {choice.map((c) => `${c.label} (${c.folds} of ${c.of})`).join(", ") || "—"}.
          </p>
        </div>
      )}
      <p className="table-caption">
        {all ? `All ${t.pipelines.length} preregistered pipelines and personalization controls.` : "Selected comparison: the rule’s choice, the current recipe, persistence and the best of each tree configuration."}{" "}
        <button type="button" className="text-btn" aria-expanded={all} onClick={() => setAll((x) => !x)}>
          {all ? "Show selected comparison" : "Show all pipelines"}
        </button>
      </p>
      <div className={`table-scroll${all ? " table-scroll--sticky" : ""}`} tabIndex={0} role="region" aria-label="Held-out comparison table">
        <table className="table">
          <caption className="visually-hidden">Macro mean absolute error on outer-fold participants</caption>
          <thead>
            <tr>
              <th scope="col">Pipeline</th>
              <th scope="col" className="num">MAE 30 min</th><th scope="col" className="num">MAE 60 min</th>
              {all && <th scope="col" className="num">RMSE 30 min</th>}{all && <th scope="col" className="num">RMSE 60 min</th>}
              <th scope="col" className="num" title="Origins whose observed target exceeded 180 mg/dL">{RESEARCH_LABELS.highGlucose}, 60 min</th>
              <th scope="col" className="num" title={LABELS.availabilityHelp}>{LABELS.availability}</th>
              {all && <th scope="col" className="num" title={LABELS.latencyHelp}>Inference / 1,000</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => <PipelineRow key={`${p.pipeline}|${p.mode}`} p={p} all={all} />)}
          </tbody>
        </table>
      </div>
      <p className="helper">{LABELS.maeHelp} mg/dL, macro over people. {RESEARCH_LABELS.highGlucose}: error on forecasts whose observed
        target exceeded 180 mg/dL, where large misses matter most. {LABELS.availability}: {LABELS.availabilityHelp} RMSE and inference time are in
        the full view.</p>
    </>
  );
}

function PipelineRow({ p, all }: { p: ResearchPipeline; all: boolean }) {
  const a = p.horizons["30"], b = p.horizons["60"];
  return (
    <tr className={p.pipeline === "selected" && p.mode === "final" ? "row-serving" : undefined}>
      <th scope="row" className="table__name">{p.display}<span className="table__sub">{p.pipeline} · {p.mode}</span></th>
      <td className="num">{fmtNum(a?.mae, 2)}</td><td className="num">{fmtNum(b?.mae, 2)}</td>
      {all && <td className="num">{fmtNum(a?.rmse, 2)}</td>}{all && <td className="num">{fmtNum(b?.rmse, 2)}</td>}
      <td className="num" title={b?.high_glucose_participants != null ? `${b.high_glucose_participants} people with at least 20 such forecasts` : undefined}>
        {fmtNum(b?.mae_high_glucose_target, 2)}</td>
      <td className="num">{fmtPct(b?.availability, 1)}</td>
      {all && <td className="num">{fmtLatency(p.inference_ms_per_1k)}</td>}
    </tr>
  );
}

function Paired({ rows, title }: { rows: ResearchComparison[]; title: string }) {
  const shown = rows.filter((c) => c.mean_diff != null);
  if (!shown.length) return null;
  return (
    <Disclosure title={title} summary="Paired per-person differences, participant-cluster bootstrap (2,000 resamples)">
      <div className="table-scroll" tabIndex={0} role="region" aria-label={title}>
        <table className="table">
          <thead><tr><th scope="col">Comparison (a minus b)</th><th scope="col" className="num">Horizon</th><th scope="col" className="num">Mean difference</th>
            <th scope="col" className="num">95% interval</th><th scope="col" className="num">Improved / worsened</th></tr></thead>
          <tbody>
            {shown.map((c, i) => (
              <tr key={i}><td>{c.comparison}</td><td className="num">{c.horizon} min</td><td className="num">{fmtSigned(c.mean_diff)} mg/dL</td>
                <td className="num">{fmtSigned(c.ci95[0])} to {fmtSigned(c.ci95[1])}</td><td className="num">{c.improved} / {c.worsened} of {c.n_participants}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="helper">Negative means the first pipeline had lower error. People are resampled, not forecast times, because one person’s overlapping forecasts are not independent.</p>
    </Disclosure>
  );
}

function Ranges({ t }: { t: ResearchTrack }) {
  const sel = t.pipelines.find((p) => p.pipeline === "selected" && p.mode === "final");
  if (!sel) return null;
  const g = (h: string) => sel.intervals[h]?.global as Dict | undefined;
  return (
    <Disclosure title="Prediction ranges"
      summary={`${RESEARCH_LABELS.coverageTarget} 80% · ${RESEARCH_LABELS.coverageMeasured.toLowerCase()} ${fmtPct(num(g("30")?.coverage_pooled), 1)} / ${fmtPct(num(g("60")?.coverage_pooled), 1)} at 30 / 60 min`}>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Prediction range coverage">
        <table className="table">
          <thead><tr><th scope="col">Method</th><th scope="col" className="num">Horizon</th><th scope="col" className="num">{RESEARCH_LABELS.coverageMeasured} (pooled)</th>
            <th scope="col" className="num">Per person (macro)</th><th scope="col" className="num">Person range</th><th scope="col" className="num">Mean width</th>
            <th scope="col" className="num">Interval score</th><th scope="col" className="num">Low / usual / high glucose</th></tr></thead>
          <tbody>
            {(["30", "60"] as const).flatMap((h) => (["global", "cls"] as const).map((m) => {
              const s = (sel.intervals[h]?.[m] ?? {}) as Dict;
              const st = (s.by_current_glucose ?? {}) as Record<string, Dict>;
              return (
                <tr key={h + m}>
                  <td>{m === "global" ? "Split-conformal (primary)" : <>Locally scaled (secondary)<span className="table__sub">global fallback {fmtPct(num(s.fallback_rate), 1)} of forecasts</span></>}</td>
                  <td className="num">{h} min</td><td className="num">{fmtPct(num(s.coverage_pooled), 1)}</td><td className="num">{fmtPct(num(s.coverage_macro), 1)}</td>
                  <td className="num">{fmtPct(num(s.coverage_participant_min), 0)}–{fmtPct(num(s.coverage_participant_max), 0)}</td>
                  <td className="num">{fmtNum(num(s.width_mean), 1)} mg/dL</td><td className="num">{fmtNum(num(s.interval_score_macro), 1)}</td>
                  <td className="num">{["low", "usual", "high"].map((k) => (st[k]?.coverage == null ? "n/a" : fmtPct(num(st[k].coverage), 0))).join(" / ")}</td>
                </tr>
              );
            }))}
          </tbody>
        </table>
      </div>
      <p className="helper">Ranges are calibrated on separate calibration people for the exact final pipeline, aiming at 80%. Measured coverage is a result, not a
        guarantee; “n/a” marks glucose strata with too few observations. The interval score rewards narrow ranges and penalises misses. Endpoints are never clipped.</p>
    </Disclosure>
  );
}

function WarningsTable({ w }: { w: Dict }) {
  const pol = ((w.policies ?? []) as Dict[]).filter((p) => p.horizon === 60);
  const prim = pol.find((p) => p.pipeline === "selected" && p.policy === "primary");
  return (
    <Disclosure title="Research warnings"
      summary={prim && prim.status === "ok"
        ? `Selected pipeline, primary policy: ${prim.detected_onsets} of ${prim.true_onsets} onsets, ${fmtNum(num(prim.false_alarms_per_observed_day), 2)} false alarms per observed day`
        : "60-minute horizon on held-out people"}>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Warning trade-offs">
        <table className="table">
          <thead><tr><th scope="col">Pipeline and policy</th><th scope="col" title={RESEARCH_LABELS.recallHelp} className="num">{RESEARCH_LABELS.recall}</th>
            <th scope="col" className="num">Missed / onsets</th><th scope="col" title={RESEARCH_LABELS.precisionHelp} className="num">{RESEARCH_LABELS.precision}</th>
            <th scope="col" className="num" title={RESEARCH_LABELS.falseAlarmsObservedHelp}>{RESEARCH_LABELS.falseAlarmsObserved}</th>
            <th scope="col" className="num">{RESEARCH_LABELS.falseAlarmsEligible}</th><th scope="col" className="num">Censored</th>
            <th scope="col" className="num" title={LABELS.qualifiedLeadHelp}>{LABELS.qualifiedLead}</th><th scope="col">Thresholds by fold</th></tr></thead>
          <tbody>
            {pol.map((p, i) => (
              <tr key={i} className={p.pipeline === "selected" && p.policy === "primary" ? "row-serving" : undefined}>
                <td>{String(p.display)}<span className="table__sub">{POLICY[String(p.policy)] ?? String(p.policy)}</span></td>
                {p.status !== "ok" ? <td colSpan={8} className="muted">No threshold met this budget on the inner folds</td> : <>
                  <td className="num">{fmtNum(num(p.recall), 2)}<span className="table__sub">{fmtNum(num((p.recall_ci95 as number[])?.[0]), 2)}–{fmtNum(num((p.recall_ci95 as number[])?.[1]), 2)}</span></td>
                  <td className="num">{String(p.missed_onsets)} / {String(p.true_onsets)}</td>
                  <td className="num">{fmtNum(num(p.precision), 2)}</td>
                  <td className="num">{fmtNum(num(p.false_alarms_per_observed_day), 2)}<span className="table__sub">{fmtNum(num((p.false_alarms_per_observed_day_ci95 as number[])?.[0]), 2)}–{fmtNum(num((p.false_alarms_per_observed_day_ci95 as number[])?.[1]), 2)}</span></td>
                  <td className="num">{fmtNum(num(p.false_alarms_per_eligible_day), 2)}</td>
                  <td className="num">{String(p.censored_warnings)}</td>
                  <td className="num">{num(p.qualified_lead_median) != null ? `${p.qualified_lead_median} min` : "—"}</td>
                  <td className="nowrap">{Object.values((p.thresholds_by_fold ?? {}) as Record<string, number | null>).map((v) => (v == null ? "none" : fmtSigned(v, 0))).join(", ")}</td>
                </>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="helper">A warning fires when the highest forecast within 60 minutes exceeds 180 mg/dL by at least the threshold (an uncalibrated margin, not a
        probability). Thresholds were chosen on inner out-of-fold predictions of the same pipeline; sensitivity budgets are reported, never selected.
        Intervals resample people. Warnings support review; they are not treatment advice.</p>
    </Disclosure>
  );
}

function ColdStart({ t }: { t: ResearchTrack }) {
  const modes = ["off", "v2_policy", "best_grid", "frozen_state", "final"];
  const names: Record<string, string> = { off: "Population only", v2_policy: "v2 adaptation policy", best_grid: "Best grid adaptation",
    frozen_state: "Adaptation frozen after 24 h", final: "Selected personalization" };
  const rows = modes.map((m) => t.pipelines.find((p) => p.pipeline === "selected" && p.mode === m)).filter((p): p is ResearchPipeline => !!p);
  if (!rows.length) return null;
  const cell = (p: ResearchPipeline, k: string) => {
    const c = (p.horizons["60"]?.cold_start?.[k] ?? {}) as Dict;
    return <td className="num">{fmtNum(num(c.mae_macro), 2)}<span className="table__sub">{Number(c.origins ?? 0).toLocaleString()} forecasts</span></td>;
  };
  return (
    <Disclosure title="Cold start and personalization" summary="60-minute error by hours since the recording started">
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Cold start">
        <table className="table">
          <thead><tr><th scope="col">Personalization (selected pipeline)</th><th scope="col" className="num">First 6 h</th><th scope="col" className="num">6–24 h</th><th scope="col" className="num">After 24 h</th></tr></thead>
          <tbody>{rows.map((p) => <tr key={p.mode}><td>{names[p.mode]}</td>{cell(p, "first_6h")}{cell(p, "6_to_24h")}{cell(p, "after_24h")}</tr>)}</tbody>
        </table>
      </div>
      <p className="helper">Elapsed history is the time since the recording’s first reading. Adaptation stays at zero until six forecast errors have matured, so
        the first hours show the population model. Each person starts from an empty state.</p>
    </Disclosure>
  );
}

function Selection({ t }: { t: ResearchTrack }) {
  const rows = Object.entries(t.selection_by_fold as Record<string, Dict>);
  return (
    <Disclosure title="What the declared rule chose in each fold" summary="Chosen on inner folds; outer results never fed back">
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Per-fold selection">
        <table className="table">
          <thead><tr><th scope="col">Fold</th><th scope="col">Population model</th><th scope="col">Personalization</th><th scope="col">Rationale</th></tr></thead>
          <tbody>
            {rows.map(([f, s]) => {
              const ad = s.adaptation as Dict | null;
              return <tr key={f}><td className="nowrap">{f === "final" ? "Deployment candidate" : f}</td><td className="wrap-id">{String(s.selected)}</td>
                <td>{!ad || ad.name === "off" ? "Off" : `${String(ad.name)} (k ${String(ad.k)}, half-life ${String(ad.half_life)} min)`}</td>
                <td className="muted">{String(s.rationale)}</td></tr>;
            })}
          </tbody>
        </table>
      </div>
    </Disclosure>
  );
}

function External({ r }: { r: ResearchReport }) {
  const e = r.external;
  if (!e) return null;
  if (e.status !== "completed") {
    return <Disclosure title="External cohort (ShanghaiT2DM)" summary="Not run"><p>{e.reason}</p></Disclosure>;
  }
  const pipes = e.pipelines ?? [];
  const rows = pipes.filter((p) => p.mode === "off" || (p.selected && p.mode === "final"));
  const vsP = (h: number) => (e.comparisons ?? []).find((c) => c.comparison === "Selected candidate minus persistence" && c.horizon === h);
  const said = (c?: ResearchComparison) => (!c || c.mean_diff == null ? "—"
    : `${fmtSigned(c.mean_diff)} mg/dL [${fmtSigned(c.ci95[0])}, ${fmtSigned(c.ci95[1])}]${c.ci95[0] != null && c.ci95[1] != null && c.ci95[0] < 0 && c.ci95[1] > 0 ? ", inconclusive" : ""}`);
  return (
    <Disclosure title="External cohort (ShanghaiT2DM)"
      summary={`${e.participants} people · 15-minute LightGBM vs persistence: ${said(vsP(30))} at 30 min; ${said(vsP(60))} at 60 min`}>
      <p className="lede__sub">
        Against persistence on the same {e.participants} people: <strong>{said(vsP(30))}</strong> at 30 minutes
        ({vsP(30)?.improved ?? "—"} of {vsP(30)?.n_participants ?? "—"} people better) and {said(vsP(60))} at 60 minutes. Negative means lower error;
        brackets are 95% participant-bootstrap intervals.
      </p>
      <MetadataLine>
        <>Opened once {String((e.opened as Dict | null)?.opened_at ?? "").slice(0, 10)}</>
        <>Candidate <span className="wrap-id">{e.candidate}</span></>
        <>15-minute CGM only · regression and ranges (no event metric at this cadence)</>
      </MetadataLine>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="External results">
        <table className="table">
          <thead><tr><th scope="col">Pipeline (frozen before opening)</th><th scope="col" className="num">MAE 30 min</th><th scope="col" className="num">MAE 60 min</th>
            <th scope="col" className="num">RMSE 60 min</th><th scope="col" className="num">{LABELS.availability}</th><th scope="col" className="num">Range coverage 30 / 60</th></tr></thead>
          <tbody>
            {rows.map((p) => {
              const c = (h: string) => num((p.intervals[h]?.global as Dict | undefined)?.coverage_pooled);
              return (
                <tr key={p.pipeline + p.mode} className={p.selected && p.mode === "final" ? "row-serving" : undefined}>
                  <th scope="row" className="table__name">{p.display}</th>
                  <td className="num">{fmtNum(p.horizons["30"]?.mae, 2)}</td><td className="num">{fmtNum(p.horizons["60"]?.mae, 2)}</td>
                  <td className="num">{fmtNum(p.horizons["60"]?.rmse, 2)}</td><td className="num">{fmtPct(p.horizons["60"]?.availability, 1)}</td>
                  <td className="num">{fmtPct(c("30"), 1)} / {fmtPct(c("60"), 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Paired rows={e.comparisons ?? []} title="External paired differences" />
      <p className="helper">Every row was frozen before the cohort was opened. A pipeline with lower external error that the development rule did not
        choose is reported, not adopted: choosing by these results would turn the external cohort into a tuning set.</p>
      <p className="helper">Different country, device (FreeStyle Libre H), cadence and care setting from the training data. These people were never used for any
        choice. This is not an Indian cohort and not a clinical validation.</p>
    </Disclosure>
  );
}

function Handoff({ cand }: { cand: Record<string, Dict> }) {
  const c = cand.multimodal_5min;
  if (!c) return null;
  const cc = c.candidate as Dict;
  const par = c.parity as Dict | null;
  const ad = c.adaptation as Dict;
  const iv = c.intervals as Dict;
  const al = (c.alerts ?? {}) as Dict;
  return (
    <Disclosure title="Deployment candidate (not promoted)" summary={String(cc.model_version)}>
      <dl className="dl">
        <dt>Pipeline</dt><dd className="wrap-id">{String(cc.selected)} · personalization {String(cc.mode)}</dd>
        <dt>Adaptation</dt><dd>{ad.enabled ? `on (k ${String(ad.shrinkage_k)}, half-life ${String(ad.half_life_minutes)} min)` : "off"}</dd>
        <dt>Ranges</dt><dd>{Object.entries((iv.quantiles_mg_dl ?? {}) as Record<string, number | null>).map(([h, q]) => `${h} min ±${fmtNum(q, 1)} mg/dL`).join(" · ")} (target 80%)</dd>
        <dt>Warning margin</dt><dd>{al.threshold_margin_mg_dl == null ? "No threshold met the workload budget" : `${fmtSigned(num(al.threshold_margin_mg_dl), 0)} mg/dL at ${String(al.horizon_minutes)} min`}</dd>
        <dt>Online/offline parity</dt><dd>{par ? `${String(par.origins)} forecasts, largest difference ${fmtNum(num(par.max_abs_final), 6)} mg/dL before rounding; ${String(par.ms_per_origin)} ms per forecast in the engine` : "Not checked"}</dd>
        <dt>Promotion</dt><dd>Explicit and separate: <code>glucotwin research promote --track multimodal_5min --yes</code>; rollback with <code>glucotwin research rollback</code>.</dd>
      </dl>
    </Disclosure>
  );
}

function ProtocolNotes({ r }: { r: ResearchReport }) {
  return (
    <Disclosure title="Protocol and inspection history">
      <dl className="dl">
        <dt>Experiment</dt><dd className="wrap-id">{r.experiment_id} · declared {r.declared_on} · split hash {r.split_hash}</dd>
        <dt>Folds</dt><dd>{(r.folds ?? []).map((f) => `${String(f.fold)}: ${String(f.assessment)} assessed, ${String(f.calibration)} calibration, ${String(f.development)} development`).join(" · ")}</dd>
        {(r.inspection_log ?? []).map((e, i) => <Fragment key={i}><dt>{String(e.date)}</dt><dd>{String(e.what)}</dd></Fragment>)}
      </dl>
    </Disclosure>
  );
}
