"""``glucotwin`` command-line interface.

    glucotwin data download      fetch CGMacros 1.0.0 (opt-in; ~657 MB) and verify SHA-256 checksums
                                 (--dataset shanghai_t2dm: ShanghaiT2DM archive, 3.7 MB, publisher MD5 verified)
    glucotwin data verify        verify an existing local copy in data/raw/cgmacros/1.0.0
    glucotwin data import        verify + normalize into data/processed/cgmacros/v1 (idempotent)
                                 (--dataset shanghai_t2dm: canonical partitions + data/processed/shanghai/v1)
    glucotwin data canonical     write CGMacros canonical-cgm-1 partitions (model store untouched, parity checked)
    glucotwin data manifest      source manifest + reports/dataset_inventory.json + dataset_expansion_audit.md
    glucotwin data audit         write reports/data_audit.md from the import audit
    glucotwin synthetic build    build synthetic fixtures + the synthetic demonstration model (no download)
    glucotwin experiment build   build origin table, labels and split manifest
    glucotwin experiment run     run the frozen primary experiment (writes artifacts/ and registry)
    glucotwin experiment report  write reports/evaluation_report.md from saved metrics
    glucotwin research freeze    write the nested protocol's split membership (before any fit)
    glucotwin research smoke     development-only timing run (budget evidence)
    glucotwin research develop   nested development per fold/track; freezes every pipeline (no registry writes)
    glucotwin research assess    outer-fold assessment, once, from the frozen fold artifacts
    glucotwin research external  reserved ShanghaiT2DM assessment, once, with the frozen portable candidate
    glucotwin research report    reports/nested_benchmark_report.md + model_upgrade_review.md from saved predictions
    glucotwin research promote   EXPLICIT: point the registry at a frozen candidate (atomic, verified; not run by default)
    glucotwin research rollback  EXPLICIT: point the registry back to a previous serving model version
    glucotwin contracts export   export OpenAPI + example payloads to packages/contracts
    glucotwin public-evidence export  aggregate-only evidence snapshot for the public demo (reports/public_evidence/)
    glucotwin serve              start the API on 127.0.0.1:8000 (--public-demo: public synthetic demonstration)
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
    dl.add_argument("--dataset", default="cgmacros", choices=["cgmacros", "shanghai_t2dm"])
    d.add_parser("verify").add_argument("--dataset", default="cgmacros", choices=["cgmacros", "shanghai_t2dm"])
    d.add_parser("import").add_argument("--dataset", default="cgmacros", choices=["cgmacros", "shanghai_t2dm"])
    d.add_parser("canonical")
    d.add_parser("manifest")
    d.add_parser("audit")

    s = sub.add_parser("synthetic").add_subparsers(dest="cmd", required=True)
    s.add_parser("build")

    e = sub.add_parser("experiment").add_subparsers(dest="cmd", required=True)
    eb = e.add_parser("build")
    eb.add_argument("--experiment", default=None, help="protocol id (default: configs/experiment.yaml)")
    run = e.add_parser("run")
    run.add_argument("--experiment", default=None, help="protocol id, e.g. gt-primary-2026-10-11-v1 to reproduce v1")
    run.add_argument("--validation-only", action="store_true", help="stop before any test-segment metric")
    run.add_argument("--no-lopo", action="store_true")
    e.add_parser("report")

    r = sub.add_parser("research").add_subparsers(dest="cmd", required=True)
    for name in ("freeze", "smoke", "develop", "assess", "external", "report", "promote", "rollback"):
        rp = r.add_parser(name)
        rp.add_argument("--experiment", default="gt-nested-2026-10-12-v1")
        if name == "develop":
            rp.add_argument("--workers", type=int, default=None)
            rp.add_argument("--track", action="append", default=None)
            rp.add_argument("--fold", action="append", default=None)
        if name in ("assess", "external"):
            rp.add_argument("--reopen-reason", default=None, help="required to run an already-opened assessment again")
        if name == "promote":
            rp.add_argument("--track", default="multimodal_5min")
            rp.add_argument("--registry", default=None, help="registry path (default: artifacts/registry.json)")
            rp.add_argument("--yes", action="store_true", help="confirm switching the app's serving model")
        if name == "rollback":
            rp.add_argument("--to", required=True, help="model_version to serve again")
            rp.add_argument("--registry", default=None)

    c = sub.add_parser("contracts").add_subparsers(dest="cmd", required=True)
    c.add_parser("export")

    pe = sub.add_parser("public-evidence").add_subparsers(dest="cmd", required=True)
    pe.add_parser("export", help="write reports/public_evidence/ from the saved artifacts, as the public-mode API returns "
                                 "them; refuses anything that names or lists a participant")

    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=None, help="default: $PORT, else 8000")
    sv.add_argument("--reload", action="store_true")
    sv.add_argument("--public-demo", action="store_true",
                    help="public synthetic demonstration: synthetic participants only, sessions private per visitor, "
                         "limited and expiring (sets GLUCOTWIN_PUBLIC_DEMO=1)")

    a = ap.parse_args(argv)
    if a.group == "data":
        from glucotwin.data import acquire, pipeline

        if a.cmd in ("download", "verify", "import") and a.dataset == "shanghai_t2dm":
            from glucotwin.data import shanghai

            fn = {"download": lambda: shanghai.download(force=a.force), "verify": shanghai.verify,
                  "import": shanghai.import_shanghai}[a.cmd]
            print(json.dumps(fn(), indent=1))
        elif a.cmd == "download":
            files = acquire.download(use_mirror=not a.primary, force=a.force)
            print(json.dumps([f.__dict__ for f in files], indent=1))
        elif a.cmd == "verify":
            files = acquire.verify()
            print(f"Verified {len(files)} files against SHA256SUMS.txt")
        elif a.cmd == "import":
            print(json.dumps(pipeline.import_cgmacros(), indent=1))
        elif a.cmd == "canonical":
            print(json.dumps(pipeline.export_cgmacros_canonical(), indent=1))
        elif a.cmd == "manifest":
            from glucotwin.data import inventory
            from glucotwin.research.protocol import split_file_path

            print(json.dumps(inventory.write(split_file_path()), indent=1))
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
            from glucotwin.dataset import build_origin_table, experiment_dir, load_settings

            store = Store(dataset_store_dir())
            if not store.exists():
                print("CGMacros store not found; run `glucotwin data import` first.", file=sys.stderr)
                return 2
            st = load_settings(experiment_id=a.experiment)
            m = build_origin_table(store, st, experiment_dir(dataset_store_dir(), st.raw["experiment"]["experiment_id"]))
            print(json.dumps(m["summary"], indent=1))
        elif a.cmd == "run":
            from glucotwin.evaluation.run import run as run_exp

            run_exp(include_lopo=not a.no_lopo, stop_before_test=a.validation_only, experiment_id=a.experiment)
        elif a.cmd == "report":
            from glucotwin.reports import write_evaluation_report

            print(write_evaluation_report())
    elif a.group == "research":
        from glucotwin.research import runner

        if a.cmd == "freeze":
            out = runner.do_freeze(a.experiment)
        elif a.cmd == "smoke":
            out = runner.do_smoke(a.experiment)
        elif a.cmd == "develop":
            out = runner.do_develop(a.experiment, a.workers, tuple(a.track or runner.TRACKS), a.fold)
        elif a.cmd == "assess":
            out = runner.do_assess(a.experiment, a.reopen_reason)
        elif a.cmd == "external":
            out = runner.do_external(a.experiment, a.reopen_reason)
        elif a.cmd == "report":
            from glucotwin.research.report import write_reports

            out = write_reports(a.experiment)
        elif a.cmd == "promote":
            from glucotwin.research.promote import promote

            out = promote(a.experiment, a.track, a.registry, confirm=a.yes)
        else:
            from glucotwin.research.promote import rollback

            out = rollback(a.to, a.registry)
        print(json.dumps(out, indent=1, default=str))
    elif a.group == "contracts":
        from glucotwin_api.contracts import export

        print(export())
    elif a.group == "public-evidence":
        from glucotwin_api import snapshot

        print(json.dumps(snapshot.export(), indent=1))
    elif a.group == "serve":
        import os

        import uvicorn

        if a.public_demo:
            os.environ["GLUCOTWIN_PUBLIC_DEMO"] = "1"
        port = a.port if a.port is not None else int(os.environ.get("PORT", "8000"))
        uvicorn.run("glucotwin_api.app:app", host=a.host, port=port, reload=a.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
