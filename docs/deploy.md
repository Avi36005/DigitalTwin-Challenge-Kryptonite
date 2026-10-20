# Deploying the public synthetic demonstration

**Status: not deployed.** Publishing makes the app reachable by anyone on the internet, so it needs the team's
explicit approval and a decision on which account hosts it. Nothing in this repository deploys automatically.

## What gets deployed

The opt-in public mode (`GLUCOTWIN_PUBLIC_DEMO=1`, decision D-047): one process serves the API and the built web app,
synthetic participants only. The [`Dockerfile`](../Dockerfile) builds it from Git-tracked sources only — the
[`.dockerignore`](../.dockerignore) is an allow-list (`pyproject.toml`, `uv.lock`, `README.md`, `LICENSE`, `ml/`,
`services/`, `packages/`, `configs/`, `apps/web/`) — and generates the fictional synthetic fixtures and the synthetic
demonstration model at build time. It contains **no recorded CGMacros or ShanghaiT2DM data** and no saved experiment
files. The Model evidence page instead shows the aggregate-only published snapshot in `reports/public_evidence/`
(`glucotwin public-evidence export`; participant IDs, aliases and per-participant rows refused at export), labelled
with its export date and commit. Re-export after any change to the saved results.

Enforced by the backend ([`public.py`](../services/api/glucotwin_api/public.py), tests in
[`test_public_demo.py`](../tests/test_public_demo.py)):

* each browser gets a random `gt_visitor` cookie and sees and controls only its own replays (only the hash is stored);
* recorded-data requests return 403 `public_demo_synthetic_only`;
* at most 5 replays per visitor and 300 in total (least recently used removed first), removed after 120 idle minutes;
* rate limits of 600 requests per minute per visitor and 1,200 per IP (429 `rate_limited`);
* replays live in memory: a restart clears them, and an open page then says the replay expired.

Limits can be changed with `GLUCOTWIN_PUBLIC_SESSION_IDLE_MINUTES`, `GLUCOTWIN_PUBLIC_MAX_SESSIONS_PER_VISITOR`,
`GLUCOTWIN_PUBLIC_MAX_SESSIONS`, `GLUCOTWIN_PUBLIC_VISITOR_RPM` and `GLUCOTWIN_PUBLIC_IP_RPM`.

## Run it locally first

```bash
docker compose up --build          # http://localhost:7860, published on the host's loopback only
cd apps/web && PUBLIC_BASE_URL=http://127.0.0.1:7860 npx playwright test --config playwright.public.config.ts
docker compose down
```

The browser checks cover a fresh visitor, a replay with forecasts and warnings, a page refresh, two simultaneous
visitors who cannot see or control each other's replays, and the evidence pages and their in-app links. Without
`PUBLIC_BASE_URL` the same config builds the web app and starts its own public-mode server on port 8040.

## Hugging Face Spaces (Docker)

1. Create a Space with the **Docker** SDK under the account the team chooses.
2. Push only Git-tracked files of this repository to the Space repository (for example `git archive HEAD | tar -x -C
   <space-checkout>`), never `data/`, `artifacts/`, `var/`, `context.md` or any git-excluded folder. The allow-list
   `.dockerignore` keeps anything else out of the image even if it is present.
3. The Space reads its settings from the front matter of the **Space repository's** README. Put this block at the top of
   that README (the Space's copy, not this repository's README):

   ```yaml
   ---
   title: GlucoTwin synthetic demonstration
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```

4. In the Space settings, add the variables `GLUCOTWIN_COOKIE_SECURE=1` (the Space is served over HTTPS) and
   `GLUCOTWIN_TRUST_PROXY=1` (requests arrive through the Space proxy, so the per-IP limit reads the first
   `X-Forwarded-For` hop). The image already runs as uid 1000 and listens on `$PORT` (7860), as Spaces expect.
5. After the build, check it as a visitor:
   `cd apps/web && PUBLIC_BASE_URL=https://<space-subdomain>.hf.space npx playwright test --config playwright.public.config.ts`.
6. Add the link to the README (*Public demonstration*), the judge guide and the deck, labelled synthetic only.

## Taking it down

Pause or delete the Space from its settings (Settings → Pause Space, or Delete this Space). Remove the link from the
README, the judge guide and the deck in the same commit, so no document points to a dead page.
