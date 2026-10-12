# Frontend handoff (`apps/web`)

React 19 + TypeScript 5.9 + Vite 8; React Router 7 (data router with lazy routes); TanStack Query 5; Recharts 3;
Lucide icons; Inter bundled via `@fontsource-variable/inter/opsz.css` (no runtime font download). The interface
follows the team's redesign brief of 11 October 2026 (`docs/decisions.md` D-029).

## Visual system

* **Flat, white, editorial.** Every surface is `#FFFFFF`. Hierarchy comes from position, spacing, type and 1 px
  dividers (`#E5E7EB`), not from cards. There are no repeated rounded boxes, decorative waves, glows, gradients,
  KPI tiles or pills on descriptive metadata. Contained surfaces are kept only for real overlays (dialogs, drawers,
  menus, tooltips — the only elements with a shadow), controls and the landing-page preview.
* **Black, white and blue.** Near-black text (`#111827`), secondary `#475569` and `#64748B`. One blue (`#2563EB`,
  text `#1D4ED8`) marks the selected route, links, the primary action and every model forecast. Amber and red appear
  only as small markers next to words, for real warnings or errors.
* **Type.** Inter everywhere, including chart text and identifiers. Body 14.5 px, page title 28 px, section 17 px,
  metadata 12.5–13 px, glucose values 38 px; weights 400/500/600. Tabular numerals are used for times, glucose and
  scores. Uppercase appears only in the landing eyebrow.
* **Spacing and shape.** 4 px scale; page padding 32/24/16 px (desktop / laptop / phone); control radius 6 px; dialog
  radius 12 px. Motion is 140 ms and disabled under reduced motion; charts never animate on polling.
* Tokens live only in `src/styles/tokens.css`. The few raw chart colours in `GlucoseChart.tsx` and
  `LandingPreview.tsx` mirror them.

## Routes

URLs are built only in `src/lib/routes.ts`.

| Path | Screen |
|---|---|
| `/` | Landing page (outside the workspace shell; no sidebar in its DOM). Survives an unreachable API. |
| `/app` | Overview: recent replays as divided rows, plus "Start a new replay" |
| `/app?session=<id>` | Replay workspace for that session (never created or reset by opening it) |
| `/app/participants` · `/app/sessions` · `/app/evidence` · `/app/data-quality` | Participant table · replay sessions · model evidence · data quality |

**Compatibility.** `/?session=<id>` and `/participants`, `/sessions`, `/evidence`, `/data-quality` redirect with
*replace* (so Back does not loop), keeping their query string and hash. An unknown session shows "Replay session not
found" and never opens another participant.

**Scroll and focus.** `ScrollRestoration` starts a new page at the top and restores the position on Back/Forward. A
new primary navigation moves focus to the page heading. Polling never moves the page. The window is the only vertical
scroller on phones.

## Shell

* **Sidebar:** white, 240 px, or a 64 px rail (user preference, or automatically between 761 and 1024 px). It holds:
  - the wordmark and a single **New replay** button;
  - search (⌘K / Ctrl K, ignored while typing);
  - navigation: Overview, Participants, Replay sessions, Model evidence, Data quality;
  - up to five recent replays with *View all*;
  - Preferences, Help & demo guide, and "Local research workspace".
* **Rail:** controls keep accessible names, and tooltips appear on hover and on keyboard focus.
* **Selected route:** blue text and icon with a 2 px marker. White text never sits on the white sidebar.
* **Top bar (56 px):** breadcrumb (Overview › participant) and the data mode as text ("Recorded-data replay" /
  "Synthetic demonstration").
* **Phones:** a menu button opens a native modal drawer (focus moves inside, Escape closes it, focus returns to the
  opener, navigation closes it), plus one New replay action.

## Replay workspace (`pages/ReplayPage.tsx`)

1. **Header.** The participant alias is the h1. Under it, quiet context: cohort, data mode, dataset, and replay state
   at the replay time. The participant switcher resumes or creates that participant's own session and never resets
   the current one.
2. **Baseline line.** Age, sex, BMI, HbA1c and fasting glucose, as known at the replay clock. *Profile details*
   shows sources and availability. When the model version says so, a note states that the model does not use these
   values. Missing values read "Not available", never 0.
3. **Summary group (flat, no boxes).**
   - Current glucose: black, with observation time, age and the observed 15-minute change.
   - 30- and 60-minute forecasts: blue, with "Range a–b mg/dL", target time and issue time.
   - One line "Prediction range · target coverage 80 %"; *Details* shows the measured test coverage for this model
     version, or says none exists.
   - Unavailable forecasts show "—" plus one reason: model unavailable, no data yet, abstention (e.g. "2 readings in
     the last hour; more recent history is required"), or out of date. Loading is never shown as absence.
4. **Chart.** Title, 3/6/12/24 h, earlier-forecast choice and Table view sit above the plot (360 px desktop, 280 px
   phone). The replay controls sit directly below it.
5. **Inspector (300 px; below the chart under 1180 px).** Review status, then data quality, then *View forecast
   details*. Review status is one of:
   - Warning issued
   - No warning issued (never "safe")
   - Already-high glucose state
   - Insufficient information
   - Model unavailable

   The forecast margin is shown with its threshold and "not a probability".
6. **Below the chart.** Three columns:
   - Observations, released only;
   - Warnings, chronological: first warning, last supporting forecast, outcome, and *Mark as reviewed* (a local note);
   - Model details: version, adaptation status, and population vs correction per horizon.
7. **Forecast details** is a right-side drawer. It shows identity, information cutoff, evaluation period, input
   quality, population/correction/forecast/range per horizon with the measured coverage, and factual explanations
   labelled by kind.

**Warning outcomes** show the qualified *forecast lead* (from the earliest warning whose own 60-minute horizon
contained the onset; never more than the horizon) and, when different, "first warning … before" for the whole
episode.

## Chart semantics (`GlucoseChart`)

* **Observed glucose:** black line, broken across gaps longer than 15 minutes; no interpolation.
* **Latest forecasts:** filled blue points at the 30- and 60-minute targets, with range whiskers when calibrated. No
  curve is drawn between them.
* **Earlier forecasts:** small, faint hollow circles. Selecting one draws a hollow diamond with a dashed whisker, a
  dashed "Selected forecast issued" line, and a comparison with outcomes available by the clock.
* **Markers:** a vertical "Replay clock HH:MM" line, a "Forecasts" label over the future area (6 h windows and
  shorter), a dashed amber "Research threshold 180", and meal logs as brown triangles on the bottom rail (context only,
  not a model input).
* **Tooltip:** value, timestamp, record type, and the issue and target time for forecasts.
* **Y axis:** grows to include real extremes, but does not shrink back within the same session revision and window,
  so it never jumps.

## Model evidence (`pages/EvidencePage.tsx`)

1. Correction notice when `corrects_experiment_id` is set.
2. Flat context row: dataset, evaluated participants, final-test segment, serving model.
3. "Selected pipeline" sentence, built from the report.
4. Comparison table (serving, persistence, linear trend, ridge, closest comparable candidate), chosen by rule, never
   by score, with *Show all configurations*. The full table adds RMSE, participants, **Forecast availability** and
   batch inference time (shown as "<0.1 ms" when below 0.1).
   - Rule-ordered until a heading is sorted; sortable headings set `aria-sort`.
   - A sentence explains the validation-based selection.
5. Disclosures:
   - uncertainty (paired differences with participant-cluster intervals);
   - prediction ranges (target vs measured coverage, widths, per-participant range);
   - research warnings (raw counts, both time bases, qualified lead and episode-start-to-onset);
   - per-participant variation;
   - secondary analyses (leave-one-out labelled secondary; Chronos-Bolt "Not run");
   - protocol.
6. A limitations summary with its full list.

Metric labels and their meaning are unit-tested in `src/lib/evidence.test.ts`.

## State ownership

* Network access only in `src/api/client.tsx` (typed with generated contract types) via a `Transport`.
* Replay hooks (`src/state/replay.ts`):
  - every session-scoped key is `[name, sessionId, revision, clockAt]`;
  - responses from another revision are rejected;
  - released events are accumulated with cursors, reset on a new revision and restarted after `409`;
  - `loaded` tells loading apart from "no observation released".
* The selected earlier forecast is looked up in the current revision and cleared after a rewind.
* The evaluation report is fetched once (`src/state/evaluation.ts`). The landing page makes only this one optional
  request and simply omits its research-context line when the API is down.

## Landing page (`pages/LandingPage.tsx`)

* **Content:** navigation (How it works, Model evidence, Open workspace; a small menu on phones), a hero with the
  supplied copy, an authentic preview, three numbered steps, a research-context line, a closing action and a footer.
* **Preview (`components/landing/LandingPreview.tsx`):**
  - a static SVG of one synthetic-demonstration snapshot captured by `scripts/landing_preview.py` (fictional
    participant, synthetic demonstration model) and labelled as such;
  - no session, no polling and no controls inside it;
  - a narrower drawing on phones keeps its text readable.

## Fixture / API configuration

* **Default:** the real API through the Vite proxy (`/api` → `GLUCOTWIN_API_URL`, default `http://127.0.0.1:8000`).
* **Fixtures:** `VITE_GLUCOTWIN_TRANSPORT=fixtures` enables a bannered static transport for UI development only.
* **Failures:** a failed real request is never replaced by example data.

## Accessibility

* Landmarks, a skip link, and visible 2 px focus outlines.
* Every icon-only control is named. Visible labels are contained in accessible names ("Play" → "Play replay").
* Status always has words.
* The chart has a text summary and a table view. Tables use `scope`, sortable headings use `aria-sort`, and wide
  tables scroll sideways inside a labelled region with the participant column pinned.
* Only significant changes are announced. Reduced motion is honoured.

This is not an accessibility certification.

## Verification (11 Oct 2026)

* `npm run typecheck`, `npm test` (34 Vitest tests), `npm run build`.
* `npm run e2e` (13 Playwright tests) on its own API (`:8010`, throwaway `GLUCOTWIN_VAR_DIR`) and web server
  (`:5180`):
  - replay journey;
  - missing, stale and abstention states;
  - recorded-data ranges and drawer;
  - evidence semantics, sorting and data quality;
  - API failure, and landing without the API;
  - recording-resolution sequence (Participant 01, Participant 12);
  - mobile drawer and landing;
  - landing actions;
  - old-URL redirects (same session, clock unchanged, Back works);
  - heading focus and scroll on navigation.

  Screenshots go to `reports/ui/`.
* **Layouts:** no page-level horizontal overflow on any page at 390, 768, 1024, 1280 and 1440 px.

## Known gaps

* Sessions are held in API memory; restarting the API ends them, and the UI says so when one is reopened.
* Only one dataset is wired.

## Additions for prompt pack v4 (2026-10-12)

* **Model evidence** has an *Evidence* selector (`?experiment=` in the URL). A one-line *Serving model* statement sits
  above every report and says whether the selected experiment produced it. The nested research experiment renders
  `components/evidence/ResearchEvidence.tsx`: track tabs (5-minute / 15-minute portable), a rule-chosen default
  comparison with “Show all pipelines”, and disclosures for paired differences, ranges, warnings (both workload
  denominators), cold start, per-fold selection, the external cohort, the frozen candidate and the inspection history.
* **Data quality** gains *Data sources and scale* from `/api/v1/datasets`: publisher-reported people (external
  metadata) beside imported/eligible people, native readings and observed hours of one device definition, and the
  steps only the user can complete for access-blocked sources. The summary sentence appears only when assessed counts
  are verified.
* **Participants** filters, sorts and pages on the server (`total` = all matches); search is debounced.
