# GlucoTwin public synthetic demonstration: one process serves the API and the built web app.
# Builds only from Git-tracked sources (allow-list in .dockerignore), generates the fictional synthetic fixtures and the
# synthetic demonstration model at build time, and contains no recorded patient data. Recorded-data (CGMacros) replays
# run only on a local install (`make data`), never in this image.
#   docker compose up --build   →   http://localhost:7860

FROM node:24-bookworm-slim AS web
WORKDIR /src
COPY apps/web/package.json apps/web/package-lock.json apps/web/
RUN cd apps/web && npm ci --no-audit --no-fund
COPY packages packages
COPY apps/web apps/web
RUN cd apps/web && npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.14 /uv /usr/local/bin/
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
USER app
WORKDIR /home/app/glucotwin
COPY --chown=app pyproject.toml uv.lock README.md LICENSE ./
COPY --chown=app ml ml
COPY --chown=app services services
COPY --chown=app configs configs
COPY --chown=app reports/public_evidence reports/public_evidence
RUN uv sync --frozen --no-dev && .venv/bin/glucotwin synthetic build
COPY --from=web --chown=app /src/apps/web/dist apps/web/dist

ENV GLUCOTWIN_HOME=/home/app/glucotwin GLUCOTWIN_PUBLIC_DEMO=1 GLUCOTWIN_WEB_DIST=/home/app/glucotwin/apps/web/dist PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "exec .venv/bin/glucotwin serve --public-demo --host 0.0.0.0 --port \"$PORT\""]
