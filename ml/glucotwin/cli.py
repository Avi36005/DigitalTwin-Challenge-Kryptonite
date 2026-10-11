"""``glucotwin`` command-line interface.

    glucotwin data download      fetch CGMacros 1.0.0 (opt-in; ~657 MB) and verify SHA-256 checksums
    glucotwin data verify        verify an existing local copy in data/raw/cgmacros/1.0.0
    glucotwin data import        verify + normalize into data/processed/cgmacros/v1 (idempotent)
    glucotwin data audit         write reports/data_audit.md from the import audit
    glucotwin synthetic build    build synthetic fixtures + the synthetic demonstration model (no download)
    glucotwin experiment build   build origin table, labels and split manifest
    glucotwin experiment run     run the frozen primary experiment (writes artifacts/ and registry)
    glucotwin experiment report  write reports/evaluation_report.md from saved metrics
    glucotwin contracts export   export OpenAPI + example payloads to packages/contracts
    glucotwin serve              start the API on 127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="glucotwin", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="group", required=True)

    d = sub.add_parser("data").add_subparsers(dest="cmd", required=True)
    dl = d.add_parser("download")
    dl.add_argument("--primary", action="store_true", help="use physionet.org instead of the open-data mirror")
    dl.add_argument("--force", action="store_true")
    d.add_parser("verify")
    d.add_parser("import")
    d.add_parser("audit")

    s = sub.add_parser("synthetic").add_subparsers(dest="cmd", required=True)
    s.add_parser("build")

    e = sub.add_parser("experiment").add_subparsers(dest="cmd", required=True)
    e.add_parser("build")
    run = e.add_parser("run")
    run.add_argument("--validation-only", action="store_true", help="stop before any test-segment metric")
    run.add_argument("--no-lopo", action="store_true")
    e.add_parser("report")

    c = sub.add_parser("contracts").add_subparsers(dest="cmd", required=True)
    c.add_parser("export")

    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")

    a = ap.parse_args(argv)
    if a.group == "data":
        from glucotwin.data import acquire, pipeline

        if a.cmd == "download":
            files = acquire.download(use_mirror=not a.primary, force=a.force)
            print(json.dumps([f.__dict__ for f in files], indent=1))
        elif a.cmd == "verify":
            files = acquire.verify()
            print(f"Verified {len(files)} files against SHA256SUMS.txt")
        elif a.cmd == "import":
            print(json.dumps(pipeline.import_cgmacros(), indent=1))
        elif a.cmd == "audit":
            from glucotwin.reports import write_data_audit

            print(write_data_audit())
    elif a.group == "synthetic":
        from glucotwin.data.pipeline import build_synthetic
        from glucotwin.synthetic_model import train

        print(json.dumps(build_synthetic()))
        print(json.dumps(train()))
    elif a.group == "experiment":
        if a.cmd == "build":
            from glucotwin.data.pipeline import dataset_store_dir
            from glucotwin.data.store import Store
            from glucotwin.dataset import build_origin_table, load_settings

            store = Store(dataset_store_dir())
            if not store.exists():
                print("CGMacros store not found; run `glucotwin data import` first.", file=sys.stderr)
                return 2
            m = build_origin_table(store, load_settings(), dataset_store_dir() / "experiment")
            print(json.dumps(m["summary"], indent=1))
        elif a.cmd == "run":
            from glucotwin.evaluation.run import run as run_exp

            run_exp(include_lopo=not a.no_lopo, stop_before_test=a.validation_only)
        elif a.cmd == "report":
            from glucotwin.reports import write_evaluation_report

            print(write_evaluation_report())
    elif a.group == "contracts":
        from glucotwin_api.contracts import export

        print(export())
    elif a.group == "serve":
        import uvicorn

        uvicorn.run("glucotwin_api.app:app", host=a.host, port=a.port, reload=a.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
