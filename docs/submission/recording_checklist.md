# GlucoTwin — recording checklist

From [`docs/demo_script.md`](../demo_script.md); keep the two in step. Read aloud only the quoted lines of the script.

## Before recording

1. Running model confirmed on `/app/evidence` and equal to the model these values were recorded against
   (`lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`; else re-record every † value first).
2. Browser 1920×1080 (or 1440×900), zoom 100 %, one tab, notifications off; deck PDF
   (`docs/submission/GlucoTwin_Presentation.pdf`) open in a second window at slide 1.
3. Fresh replays: no earlier reviews on Participant 01 (a reviewed warning changes Scene 6).
4. Timer running; scene start times noted live for the YouTube chapters.

## Running order (planned times; only the rehearsal and the rendered file measure them)

| Time | Surface | Scenes | Shown |
|---|---|---|---|
| 00:00–02:00 | Slides | 1 · Opening, problem, team, twin concept | Slides 1–4 |
| **02:00** | **Switch to the app** | | |
| 02:00–05:30 | App | 2–3 · Inputs, sources, quality; forecast components and bounded personalisation | Participant 01, Day 9 · 20:38 |
| 05:30–06:15 | Slide | 4 · Architecture cutaway | Slide 7 |
| 06:15–10:00 | App | 5–7 · Pinned outcome, warnings and review, sensor gap (stale, abstain, recover) | Participant 01, Participant 12 |
| 10:00–10:45 | Slide | 8 · Results cutaway | Slide 11 |
| 10:45–14:15 | App | 9–11 · Model evidence, rewind and parity, research studies | Model evidence, Participant 12 |
| 14:15–15:00 | Slides | 12 · Closing | Slides 13, 14 |
| 15:00–20:30 | App-led | 13–17 · Synthetic edge cases, false alarm and queue, rising glucose, research cutaway, reproduce | Synthetic C/E, Participant 01, queue, slides 11–12, 15 |

Hold slide 15 for five seconds at the end so trimming cannot drop the video below 20:00.

## After recording (team only)

5. Rendered duration **≥ 20:00** (target 20:30). Upload as an **unlisted** YouTube video (needs the team's
   authorisation); YouTube's displayed duration must also be ≥ 20:00, and the link must play signed out.
6. Watch the export once end to end: no personal data, notifications or unrelated windows on screen.
7. Record the URL and both durations in `configs/submission.yaml` and README §8, then rerun
   `uv run --group docs python scripts/build_submission_assets.py` so slide 15 shows the link.
8. Repository link: only after the team makes the repository public, check it signed out and enter it in
   `configs/submission.yaml` (`links.repository`, max 500 characters on the form). Until then it stays pending.
9. Team folder `Kryptonite_VESIT/` (challenge format `Team Name_College Name`) is in the repository root.
10. Submit on Unstop before the recorded deadline, 24 Oct 2026, 19:00 IST.
