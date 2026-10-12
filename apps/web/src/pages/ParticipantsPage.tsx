import { ArrowRight, Search, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import type { PatientSummary } from "@/api/types";
import { fmtPct } from "@/lib/format";
import { useOpenTwin } from "@/state/open";
import { usePatientPage, usePatients, useSessions } from "@/state/replay";
import { statusWord } from "@/components/shell/Sidebar";
import { Button, EmptyState, PageHeader, Skeleton, SortTh } from "@/components/ui";

type SortKey = "alias" | "days" | "coverage" | "meals";
const SERVER_SORT = { alias: "alias", days: "recording_days", coverage: "coverage", meals: "meals" } as const;
const PAGE = 50;

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const id = setTimeout(() => setD(v), ms);
    return () => clearTimeout(id);
  }, [v, ms]);
  return d;
}

export function ParticipantsPage() {
  const catalogue = usePatients(); // filter options only; rows come from the server-filtered page below
  const sessions = useSessions();
  const open = useOpenTwin();
  const [params] = useSearchParams();
  const focus = params.get("focus");
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"all" | "dataset_replay" | "synthetic_demo">("all");
  const [cohort, setCohort] = useState("all");
  const [primaryOnly, setPrimaryOnly] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "alias", dir: 1 });
  const focusRow = useRef<HTMLTableRowElement>(null);

  const cohorts = useMemo(() => Array.from(new Set((catalogue.data?.items ?? []).map((p) => p.cohort.label))), [catalogue.data]);
  const needle = useDebounced(q.trim(), 250);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const query = { mode: mode === "all" ? undefined : mode, cohort: cohort === "all" ? undefined : cohort,
    eligible: primaryOnly ? true : undefined, q: needle || undefined, sort: SERVER_SORT[sort.key],
    order: sort.dir === 1 ? "asc" as const : "desc" as const, limit: PAGE, cursor: cursors[cursors.length - 1] };
  const patients = usePatientPage(query);
  useEffect(() => setCursors([null]), [mode, cohort, primaryOnly, needle, sort]); // a new query starts at page 1
  const rows: PatientSummary[] = patients.data?.items ?? [];
  const total = patients.data?.total ?? 0;
  const all = { length: patients.data?.total_unfiltered ?? catalogue.data?.total ?? 0 };
  const pageStart = (cursors.length - 1) * PAGE;

  useEffect(() => {
    if (focus) focusRow.current?.scrollIntoView({ block: "center" });
  }, [focus, rows.length]);

  const sessionFor = (pid: string) => sessions.data?.items.find((s) => s.patient_id === pid);
  const filtered = q !== "" || mode !== "all" || cohort !== "all" || primaryOnly;
  const clear = () => { setQ(""); setMode("all"); setCohort("all"); setPrimaryOnly(false); };
  const onSort = (k: SortKey) => setSort((s) => ({ key: k, dir: s.key === k ? (s.dir === 1 ? -1 : 1) : 1 }));

  return (
    <>
      <PageHeader title="Participants">
        De-identified CGMacros participants and fictional synthetic participants. Baseline values appear inside a replay, as known
        at its replay time.
      </PageHeader>

      <div className="filters" role="search" aria-label="Filter participants">
        <div className="field-inline field-inline--grow">
          <label htmlFor="p-search">Search</label>
          <div className="input-icon">
            <Search size={16} aria-hidden />
            <input id="p-search" className="input" placeholder="Label, ID or cohort" value={q} onChange={(e) => setQ(e.target.value)}
              aria-label="Search participants" />
          </div>
        </div>
        <div className="field-inline">
          <label htmlFor="p-mode">Data</label>
          <select id="p-mode" className="select" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
            <option value="all">All data</option>
            <option value="dataset_replay">Recorded-data replay</option>
            <option value="synthetic_demo">Synthetic demonstration</option>
          </select>
        </div>
        <div className="field-inline">
          <label htmlFor="p-cohort">Cohort</label>
          <select id="p-cohort" className="select" value={cohort} onChange={(e) => setCohort(e.target.value)}>
            <option value="all">All cohorts</option>
            {cohorts.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <label className="check">
          <input type="checkbox" checked={primaryOnly} onChange={(e) => setPrimaryOnly(e.target.checked)} />
          Primary Type 2 analysis only
        </label>
        <span className="filters__end">
          {filtered && <Button size="sm" variant="quiet" onClick={clear}>Clear filters</Button>}
          <span className="filters__count" aria-live="polite">{total} of {all.length} match{total > PAGE ? ` · showing ${pageStart + 1}–${pageStart + rows.length}` : ""}</span>
        </span>
      </div>

      {patients.isLoading && !patients.data ? <Skeleton h={240} /> : patients.isError ? (
        <EmptyState icon={Users} title="Participants could not be loaded">{(patients.error as Error).message}</EmptyState>
      ) : all.length === 0 ? (
        <EmptyState icon={Users} title="No participants available">Import CGMacros or build the synthetic fixtures (see README).</EmptyState>
      ) : rows.length === 0 ? (
        <EmptyState icon={Search} title="No participants match these filters" action={<Button onClick={clear}>Clear filters</Button>} />
      ) : (
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Participants table (scrolls horizontally on small screens)">
          <table className="table table--rows">
            <caption className="visually-hidden">Participants</caption>
            <thead>
              <tr>
                <SortTh k="alias" label="Participant" sort={sort} onSort={onSort} className="col-sticky" />
                <th scope="col">Data and cohort</th>
                <SortTh k="days" label="Recording" sort={sort} onSort={onSort} num />
                <SortTh k="coverage" label="CGM coverage" sort={sort} onSort={onSort} num />
                <SortTh k="meals" label="Meals logged" sort={sort} onSort={onSort} num />
                <th scope="col">Baseline fields</th>
                <th scope="col">Replay</th>
                <th scope="col"><span className="visually-hidden">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const s = sessionFor(p.patient_id);
                const present = p.attributes.filter((a) => a.present_in_source).length;
                const synthetic = p.mode === "synthetic_demo";
                return (
                  <tr key={p.patient_id} ref={focus === p.patient_id ? focusRow : undefined} className={focus === p.patient_id ? "row-focus" : undefined}>
                    <th scope="row" className="col-sticky table__name">
                      {p.display_alias}
                      <span className="table__sub">{p.patient_id}</span>
                    </th>
                    <td className="col-wide">
                      {synthetic ? "Synthetic demonstration" : `Recorded · ${p.dataset.name}`}
                      <span className="table__sub">
                        {p.cohort.label}
                        {!synthetic && (p.eligible_for_primary_analysis ? " · primary analysis" : " · exploratory, outside primary analysis")}
                      </span>
                    </td>
                    <td className="num">{p.coverage.recording_days != null ? `${p.coverage.recording_days.toFixed(1)} days` : "Not available"}</td>
                    <td className="num">
                      {fmtPct(p.coverage.glucose_coverage_fraction, 1)}
                      {p.coverage.gaps_over_threshold ? <span className="table__sub">{p.coverage.gaps_over_threshold} {p.coverage.gaps_over_threshold === 1 ? "gap" : "gaps"} &gt;15 min</span> : null}
                    </td>
                    <td className="num">{p.coverage.meals_logged ?? "—"}</td>
                    <td>
                      {present} of {p.attributes.length}
                      {p.missing_fields.length > 0 && <span className="table__sub">Missing: {p.missing_fields.join(", ")}</span>}
                    </td>
                    <td className="nowrap">{s ? statusWord(s.status) : <span className="muted">—</span>}</td>
                    <td className="table__action">
                      <button type="button" className="row-action" disabled={open.isPending}
                        onClick={() => open.open(p.patient_id, p.mode)} aria-label={`${s ? "Resume" : "Open"} twin for ${p.display_alias}`}>
                        {s ? "Resume" : "Open"}<ArrowRight size={15} aria-hidden />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {(cursors.length > 1 || patients.data?.next_cursor) && (
            <div className="pager" role="navigation" aria-label="Participant pages">
              <Button size="sm" variant="quiet" disabled={cursors.length <= 1} onClick={() => setCursors((c) => c.slice(0, -1))}>Previous</Button>
              <span className="muted">Page {cursors.length} of {Math.max(1, Math.ceil(total / PAGE))}</span>
              <Button size="sm" variant="quiet" disabled={!patients.data?.next_cursor}
                onClick={() => setCursors((c) => [...c, patients.data!.next_cursor!])}>Next</Button>
            </div>
          )}
        </div>
      )}
      <p className="page-note">
        No risk ranking is shown: a participant without a current replay has unknown, not low, risk. The model was evaluated on the
        primary Type 2 cohort only; other recorded participants are exploratory. Recorded data: CGMacros 1.0.0 (CC BY-NC-SA 4.0).
      </p>
    </>
  );
}
