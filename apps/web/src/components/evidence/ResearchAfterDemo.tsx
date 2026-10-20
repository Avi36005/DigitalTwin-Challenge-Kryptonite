import type { ResearchSummaryList } from "@/api/types";
import { InlineNotice, Section, Skeleton } from "@/components/ui";
import { BASIS, evaluatedOn, findingText, openedText, TAG, TITLE, UNREADABLE } from "@/lib/researchSummaries";
import "@/styles/research-summaries.css";

/** Research run after the demo model was chosen (20 Oct): one row per experiment, one tagged line per finding. */
export function ResearchAfterDemo({ data, loading, error }: { data?: ResearchSummaryList; loading?: boolean; error?: Error | null }) {
  return (
    <Section title="Research after the demo model (20 Oct)" id="research-after-demo-model"
      description="Experiments declared before they were run, each with its own lock file. None of them is the demo model and nothing was promoted.">
      {loading ? <Skeleton h={160} /> : error ? (
        <InlineNotice tone="attention" role="alert">The research summaries could not be loaded: {error.message}</InlineNotice>
      ) : (
        <ol className="rsum" aria-label="Research after the demo model">
          {(data?.items ?? []).map((it) => (
            <li key={it.decision_id} className="rsum__row" data-status={it.status}>
              <div className="rsum__head">
                <p className="rsum__title">{TITLE[it.decision_id] ?? it.experiment_id}</p>
                <p className="rsum__meta"><span className="nowrap">{it.decision_id}</span> · <span className="nowrap">{it.experiment_id}</span></p>
                <p className="rsum__meta">Not the demo model</p>
              </div>
              {it.status === "not_run" ? (
                <p className="rsum__empty">Not run on this installation. The research steps need the downloaded datasets.</p>
              ) : it.status !== "available" ? (
                <p className="rsum__empty rsum__empty--problem" role="note">
                  {UNREADABLE[it.status]}{it.status_detail ? <span className="muted"> {it.status_detail}</span> : null}
                </p>
              ) : (
                <div className="rsum__body">
                  <p className="rsum__on">{evaluatedOn(it)}{openedText(it) ? <span className="muted">. {openedText(it)}</span> : null}</p>
                  <ul className="rsum__findings">
                    {(it.findings ?? []).map((f) => {
                      const d = findingText(it.decision_id, f);
                      return (
                        <li key={f.key} className="rsum__finding">
                          <span className="rsum__tag" data-verdict={f.verdict}>{TAG[f.verdict]}</span>
                          <span>
                            <strong>{d.tested}.</strong> <span className="num">{d.result}.</span>
                            {f.basis ? (
                              <details className="rsum__basis">
                                <summary>{BASIS[f.basis]}</summary>
                                <span>{f.basis_note}</span>
                              </details>
                            ) : null}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}
