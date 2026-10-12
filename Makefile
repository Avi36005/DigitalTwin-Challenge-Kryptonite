# GlucoTwin — local research demo. All commands run on CPU, bind to 127.0.0.1 and need no cloud account.
.PHONY: setup synthetic data-download data data-shanghai manifest experiment research research-report report contracts api web dev test test-web e2e check build clean-var

setup:            ## install Python (uv) and web (npm) dependencies
	uv sync --group dev --group docs
	cd apps/web && npm install

synthetic:        ## build fictional synthetic fixtures + the synthetic demonstration model (no download)
	uv run glucotwin synthetic build

data-download:    ## OPT-IN: download CGMacros 1.0.0 (~657 MB, CC BY-NC-SA 4.0) and verify SHA-256 checksums
	uv run glucotwin data download

data:             ## verify + normalize CGMacros into data/processed (idempotent), then write the data audit
	uv run glucotwin data import
	uv run glucotwin experiment build
	uv run glucotwin data audit

data-shanghai:    ## OPT-IN: download ShanghaiT2DM (3.7 MB, CC BY 4.0), verify the publisher MD5 and import it
	uv run glucotwin data download --dataset shanghai_t2dm
	uv run glucotwin data import --dataset shanghai_t2dm

manifest:         ## canonical CGMacros export + source manifest + reports/dataset_expansion_audit.md
	uv run glucotwin data canonical
	uv run glucotwin data manifest

research:         ## nested research experiment (ISOLATED: writes artifacts/research/, never the model registry)
	uv run glucotwin research freeze
	uv run glucotwin research develop
	uv run glucotwin research assess
	uv run glucotwin research external
	uv run glucotwin research report

research-report:  ## regenerate research reports from saved predictions only
	uv run glucotwin research report

experiment:       ## run the frozen primary experiment (writes artifacts/ and the model registry)
	uv run glucotwin experiment run
	uv run glucotwin experiment report

report:           ## regenerate reports from saved artifacts only
	uv run glucotwin data audit
	uv run glucotwin experiment report

contracts:        ## export OpenAPI + validated examples, regenerate TypeScript types
	uv run glucotwin contracts export
	cd apps/web && npm run contracts

api:              ## start the API on http://127.0.0.1:8000
	uv run glucotwin serve --host 127.0.0.1 --port 8000

web:              ## start the web app on http://127.0.0.1:5173 (proxies /api to the API)
	cd apps/web && npm run dev

dev:              ## start API and web together (Ctrl+C stops both)
	trap 'kill 0' INT TERM; uv run glucotwin serve --host 127.0.0.1 --port 8000 & (cd apps/web && npm run dev) & wait

test:             ## backend/data/model tests
	uv run pytest

test-web:         ## frontend type check, unit tests and production build
	cd apps/web && npm run typecheck && npm test && npm run build

e2e:              ## browser journeys on their own API (:8010) + web server (:5180) with throwaway storage (also writes reports/ui/*.png)
	cd apps/web && npm run e2e

check: test test-web e2e

clean-var:        ## remove local session/audit database
	rm -rf var
