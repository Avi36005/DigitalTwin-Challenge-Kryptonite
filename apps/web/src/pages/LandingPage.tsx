import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Menu, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useClient } from "@/api/client";
import { LandingPreview } from "@/components/landing/LandingPreview";
import { Wordmark } from "@/components/shell/Brand";
import { paths } from "@/lib/routes";

/**
 * Front door of the research prototype. Outside the workspace shell (no sidebar in the DOM). The only API call is the
 * small evaluation summary for the research-context line; if the API is unavailable the line is simply omitted.
 */
export function LandingPage() {
  useEffect(() => {
    document.title = "GlucoTwin · Glucose forecasting research prototype";
    return () => {
      document.title = "GlucoTwin · Research workspace";
    };
  }, []);
  return (
    <div className="landing">
      <a href="#landing-main" className="skip-link">Skip to content</a>
      <LandingNav />
      <main id="landing-main" tabIndex={-1}>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero__copy">
            <p className="eyebrow">Glucose forecasting research</p>
            <h1 id="hero-title" className="hero__title">See the next chapter of a glucose&nbsp;trace.</h1>
            <p className="hero__desc">
              Explore a patient-specific research twin that uses recent glucose and activity history to estimate glucose
              30 and 60 minutes ahead. Replay a recording, inspect each forecast and review the evidence behind it.
            </p>
            <div className="hero__actions">
              <Link to={paths.overview()} className="btn btn--primary btn--lg">Open workspace</Link>
              <Link to={paths.evidence()} className="text-link">View model evidence<ArrowRight size={16} aria-hidden /></Link>
            </div>
            <p className="hero__note">Recorded and synthetic data. Research prototype; not for clinical decisions.</p>
          </div>
          <div className="hero__preview">
            <LandingPreview />
          </div>
        </section>

        <section className="how" id="how-it-works" aria-labelledby="how-title">
          <div className="how__head">
            <h2 id="how-title" className="how__title">From recorded measurements to inspectable forecasts.</h2>
          </div>
          <ol className="how__steps">
            <li>
              <span className="how__num" aria-hidden>1</span>
              <h3>Choose a recording.</h3>
              <p>Open a de-identified research participant or a clearly labelled synthetic demonstration.</p>
            </li>
            <li>
              <span className="how__num" aria-hidden>2</span>
              <h3>Move through time.</h3>
              <p>Replay available readings and compare the observed glucose trace with forecasts issued at each moment.</p>
            </li>
            <li>
              <span className="how__num" aria-hidden>3</span>
              <h3>Inspect the evidence.</h3>
              <p>Review model identity, patient adaptation, data quality and measured evaluation results.</p>
            </li>
          </ol>
          <ResearchContext />
        </section>

        <section className="closing" aria-labelledby="closing-title">
          <div>
            <h2 id="closing-title" className="closing__title">Explore the replay workspace</h2>
            <p className="closing__text">Step through a recording and inspect what the twin forecast at each moment, using only the data it could have seen then.</p>
          </div>
          <Link to={paths.overview()} className="btn btn--primary btn--lg">Open workspace</Link>
        </section>
      </main>
      <footer className="landing-footer">
        <span className="landing-footer__brand">GlucoTwin</span>
        <span>Research prototype — not a medical device</span>
        <nav aria-label="Footer" className="landing-footer__links">
          <Link to={paths.evidence()}>Model evidence</Link>
          <Link to={paths.dataQuality()}>Data quality</Link>
        </nav>
      </footer>
    </div>
  );
}

function LandingNav() {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btnRef.current?.focus();
      }
    };
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node) && !btnRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);
  return (
    <header className="landing-nav">
      <div className="landing-nav__inner">
        <Link to={paths.landing()} className="brand" aria-label="GlucoTwin home"><Wordmark /></Link>
        <nav aria-label="Primary" className="landing-nav__links">
          <a href="#how-it-works">How it works</a>
          <Link to={paths.evidence()}>Model evidence</Link>
        </nav>
        <span className="landing-nav__spacer" />
        <button ref={btnRef} type="button" className="icon-btn icon-btn--ghost landing-nav__menu" aria-expanded={open}
          aria-controls="landing-menu" aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen((o) => !o)}>
          {open ? <X size={18} aria-hidden /> : <Menu size={18} aria-hidden />}
        </button>
        <Link to={paths.overview()} className="btn btn--primary">Open workspace</Link>
      </div>
      {open && (
        <div ref={menuRef} id="landing-menu" className="landing-menu">
          <a href="#how-it-works" onClick={() => setOpen(false)}>How it works</a>
          <Link to={paths.evidence()}>Model evidence</Link>
        </div>
      )}
    </header>
  );
}

/** "Current evaluation: …" — rendered only from the completed evaluation report, labelled with its experiment. */
function ResearchContext() {
  const client = useClient();
  const ev = useQuery({ queryKey: ["evaluation"], queryFn: ({ signal }) => client.evaluation(signal), retry: 0, staleTime: 60_000 });
  const r = ev.data;
  if (!r || r.status !== "completed" || !r.cohort || !r.dataset) return null;
  return (
    <p className="how__context">
      Current evaluation: {r.cohort.participants_included} Type 2 participants from {r.dataset.name} {r.dataset.version}
      {" "}(experiment <span className="nowrap">{r.experiment_id}</span>). <Link to={paths.evidence()}>See the measured results</Link>.
    </p>
  );
}
