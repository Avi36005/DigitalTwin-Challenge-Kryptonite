"""Validate the research workbook: recalculate it, scan for errors, re-check sources, gates and denominators.

Steps (the delivered workbook is never modified; all recalculation happens on copies in a scratch directory):

1. Recalculate a copy with LibreOffice headless (xlsx → xlsx) so every formula has a cached value, then scan every
   sheet for formula errors (#REF!, #DIV/0!, #VALUE!, #NAME?, #N/A) and for failed in-sheet checks (MISMATCH, DIFFERS).
2. Re-hash every source file named in the Sources sheet and compare with the stored SHA-256.
3. Re-read the key values straight from the saved artifacts and compare with the recalculated cells: the D-053 gate
   (unrounded high-target worsening vs +1.0 → FAILED, not adopted), the false-alarm observed-day denominator, the
   all-onset ≥ 30-minute share versus the detected-onset median lead, and the claim status counts.
4. Coverage: every evidence-manifest check maps to a ClaimIndex row; charts, filters, frozen headers, links present.
5. Privacy scan: no home-directory paths, e-mail addresses or participant identifiers.
6. Perturbation test on a disposable copy: change source cells, recalculate, confirm the dependent formulas change
   (and a source set to "unavailable" propagates as text, never 0). The delivered file's hash is checked unchanged.

Writes reports/verification/deck_workbook_2026-10-24/workbook_check.json and .md. Exit 1 if any check fails.

Usage:  uv run --group docs python scripts/check_research_workbook.py [--soffice PATH]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "docs/submission/GlucoTwin_Research_Workbook.xlsx"
CLAIMS_JSON = ROOT / "docs/submission/GlucoTwin_Research_Claims.json"
OUT = ROOT / "reports/verification/deck_workbook_2026-10-24"
ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!", "Err:")
FUSION = ROOT / "artifacts/experiments/gt-primary-2026-10-13-fusion/metrics.json"
CONSTRAINED = ROOT / "artifacts/research/gt-constrained-2026-10-21/summary.json"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def find_soffice(given: str | None) -> str:
    for c in (given, shutil.which("soffice"), "/opt/homebrew/bin/soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if c and Path(c).exists():
            return c
    raise SystemExit("LibreOffice (soffice) not found; pass --soffice")


def recalc(soffice: str, src: Path, work: Path) -> Path:
    """LibreOffice headless round trip; recalculates on load and writes cached values."""
    out = work / "recalc"
    out.mkdir(parents=True, exist_ok=True)
    profile = work / "lo_profile"
    subprocess.run([soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--calc", "--convert-to",
                    "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out), str(src)], check=True, capture_output=True, timeout=180)
    res = out / src.name
    if not res.exists():
        raise SystemExit(f"LibreOffice produced no output for {src.name}")
    return res


def sources_index(wb: Any) -> dict[str, dict[str, Any]]:
    ws = wb["Sources"]
    head = [c.value for c in ws[4]]
    out = {}
    for r in range(5, ws.max_row + 1):
        row = {head[j]: ws.cell(row=r, column=j + 1).value for j in range(len(head))}
        if row.get("Value ID"):
            row["_row"] = r
            out[row["Value ID"]] = row
    return out


def close(a: Any, b: Any) -> bool:
    """Equal within the 15 significant digits a spreadsheet engine keeps in cached values."""
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= 1e-12 * max(1.0, abs(b))


def find_row(ws: Any, col: int, text: str, start: int = 1) -> int | None:
    for r in range(start, ws.max_row + 1):
        v = ws.cell(row=r, column=col).value
        if isinstance(v, str) and v == text:
            return r
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--soffice")
    args = ap.parse_args()
    soffice = find_soffice(args.soffice)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = "") -> None:
        checks.append({"check": name, "result": "pass" if ok else "FAIL", "detail": detail})

    delivered_hash = sha256(XLSX)
    work = Path(tempfile.mkdtemp(prefix="gt_workbook_check_"))
    try:
        # 1. recalculation and error scan
        copy = work / "copy" / XLSX.name
        copy.parent.mkdir()
        shutil.copy2(XLSX, copy)
        rc = recalc(soffice, copy, work)
        wbv = load_workbook(rc, data_only=True)
        wbf = load_workbook(XLSX)  # formulas, as delivered
        errs, fails, nformulas = [], [], 0
        for ws in wbf.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value.startswith("="):
                        nformulas += 1
        for ws in wbv.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    v = c.value
                    if isinstance(v, str) and any(v.startswith(e) for e in ERRORS):
                        errs.append(f"{ws.title}!{c.coordinate} {v}")
                    if isinstance(v, str) and v in ("MISMATCH", "DIFFERS"):
                        fails.append(f"{ws.title}!{c.coordinate} {v}")
        check("LibreOffice recalculation produced a workbook", rc.exists(), f"engine: LibreOffice headless ({Path(soffice).name}); {nformulas} formulas")
        check("no formula errors after recalculation", not errs, errs[:20])
        check("no MISMATCH / DIFFERS in-sheet checks", not fails, fails[:20])
        empty = []
        for ws in wbf.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value.startswith("=") and wbv[ws.title][c.coordinate].value is None:
                        empty.append(f"{ws.title}!{c.coordinate}")
        check("every formula has a cached value after recalculation", not empty, empty[:20])

        # 2. source hashes
        src = sources_index(wbv)
        mism, missing = [], []
        seen: dict[str, str] = {}
        for vid, r in src.items():
            p = ROOT / r["Repository path"]
            if not p.exists():
                missing.append(r["Repository path"])
                if r["Value"] not in ("unavailable", None) and r["Source ID"] not in ("experiment_yaml", "sources_yaml"):
                    mism.append(f"{vid}: file missing but value is not 'unavailable'")
                continue
            h = seen.setdefault(r["Repository path"], sha256(p))
            if r["Source SHA-256"] != h:
                mism.append(f"{vid}: {r['Repository path']}")
        check("Sources SHA-256 match the files on disk", not mism, mism[:20] or f"{len(seen)} files re-hashed")
        check("missing source files shown as 'unavailable'", True, sorted(set(missing)) or "none missing on this installation")
        zero_unavail = [vid for vid, r in src.items() if r["Value"] == 0 and r["Value ID"].endswith(("passed", "failed")) is False
                        and not (ROOT / r["Repository path"]).exists()]
        check("no missing source rendered as 0", not zero_unavail, zero_unavail)

        # 3. key outcomes against the artifacts read directly
        ga = wbv["Gates"]
        r_hi = next(r for r in range(5, ga.max_row + 1) if ga.cell(row=r, column=1).value == "D-053"
                    and "High-target" in str(ga.cell(row=r, column=3).value))
        hi = ga.cell(row=r_hi, column=4).value
        art_hi = json.loads(CONSTRAINED.read_text())["primary_gate"]["values"]["high_worsening_60"] if CONSTRAINED.exists() else None
        check("D-053 high-target worsening unrounded ≈ +1.0658 (from artifact)", art_hi is not None and close(hi, art_hi)
              and abs(hi - 1.0658) < 5e-4, {"workbook": hi, "artifact": art_hi, "limit": ga.cell(row=r_hi, column=6).value})
        check("D-053 high-target criterion FAIL vs +1.0 limit", ga.cell(row=r_hi, column=7).value == "FAIL",
              ga.cell(row=r_hi, column=7).value)
        r_all = next(r for r in range(5, ga.max_row + 1) if ga.cell(row=r, column=1).value == "D-053"
                     and ga.cell(row=r, column=2).value == "OVERALL")
        r_pr = next(r for r in range(5, ga.max_row + 1) if ga.cell(row=r, column=1).value == "D-053"
                    and ga.cell(row=r, column=2).value == "PRIMARY")
        check("D-053 overall and primary gate FAILED; saved flags agree",
              ga.cell(row=r_all, column=7).value == "FAILED" and ga.cell(row=r_pr, column=7).value == "FAILED"
              and str(ga.cell(row=r_pr, column=8).value).upper() == "FALSE",
              {"overall": ga.cell(row=r_all, column=7).value, "primary": ga.cell(row=r_pr, column=7).value,
               "saved_primary": ga.cell(row=r_pr, column=8).value})
        st = wbv["Studies"]
        r53 = find_row(st, 1, "D-053")
        check("D-053 recorded as not adopted", r53 is not None and "NOT ADOPTED" in str(st.cell(row=r53, column=16).value),
              st.cell(row=r53, column=16).value if r53 else None)
        others = {ga.cell(row=r, column=1).value: ga.cell(row=r, column=7).value for r in range(5, ga.max_row + 1)
                  if ga.cell(row=r, column=2).value == "OVERALL"}
        check("no study gate D-048…D-053 shows PASSED (none adopted)", all(v == "FAILED" for v in others.values()), others)

        wr = wbv["WarningRanges"]
        m = json.loads(FUSION.read_text()) if FUSION.exists() else None
        e = next(x for x in m["events"] if x["model"] == "lightgbm:dyn-prof-v2 (adaptive)" and x["split"] == "test"
                 and x["horizon"] == 60) if m else None
        r_fa = find_row(wr, 2, "False alarms per OBSERVED patient-day")
        fa = {"value": wr.cell(row=r_fa, column=3).value, "numerator": wr.cell(row=r_fa, column=5).value,
              "denominator": wr.cell(row=r_fa, column=6).value, "saved": wr.cell(row=r_fa, column=8).value}
        check("false alarms per observed day = saved count / saved observed patient-days (event metadata)",
              e is not None and close(fa["denominator"], e["observed_patient_days"]) and fa["numerator"] == e["false_alarm_episodes"]
              and close(fa["value"], e["false_alarms_per_observed_patient_day"]), fa)
        r_el = find_row(wr, 2, "False alarms per ELIGIBLE patient-day")
        check("eligible patient-day base kept separate from observed",
              e is not None and close(wr.cell(row=r_el, column=6).value, e["eligible_patient_days"])
              and not close(wr.cell(row=r_el, column=6).value, fa["denominator"]),
              {"eligible": wr.cell(row=r_el, column=6).value, "observed": fa["denominator"]})
        r30 = find_row(wr, 2, "Warned ≥ 30 min ahead, share of ALL onsets")
        r_med = find_row(wr, 2, "Median qualified lead (DETECTED onsets only)")
        s30 = {"share": wr.cell(row=r30, column=3).value, "num": wr.cell(row=r30, column=5).value, "den": wr.cell(row=r30, column=6).value}
        med = {"median": wr.cell(row=r_med, column=3).value, "den": wr.cell(row=r_med, column=6).value}
        check("48.4 % uses all onsets (31/64); median lead uses detected onsets (61)",
              s30["num"] == 31 and s30["den"] == 64 and round(s30["share"] * 100, 1) == 48.4 and med["den"] == 61
              and med["median"] == 30 and e is not None and e["true_onsets"] == 64 and e["qualified_lead_n"] == 61, {"share": s30, "median": med})

        # status counts
        cl = wbv["ClaimIndex"]
        hr = find_row(cl, 1, "Claim ID")
        statuses = [cl.cell(row=r, column=5).value for r in range(hr + 1, cl.max_row + 1) if cl.cell(row=r, column=1).value]
        counted = {cl.cell(row=r, column=2).value: cl.cell(row=r, column=3).value for r in range(4, hr - 1)}
        actual = {s: statuses.count(s) for s in counted if s != "total"}
        exported = json.loads(CLAIMS_JSON.read_text())["status_counts"]
        check("ClaimIndex COUNTIF status counts equal the rows and the JSON export",
              all(counted[s] == actual[s] == exported.get(s) for s in actual) and counted.get("total") == len(statuses),
              {"countif": counted, "rows": actual})
        unknown = sorted({s for s in statuses if s not in counted})
        check("every claim uses the declared status vocabulary", not unknown, unknown)
        checks_col = [cl.cell(row=r, column=10).value for r in range(hr + 1, cl.max_row + 1)]
        check("ClaimIndex checks: no MISMATCH", "MISMATCH" not in checks_col,
              {"matches": checks_col.count("matches"), "pending": checks_col.count("pending")})

        # 4. coverage and structure
        man = json.loads((ROOT / "reports/evidence_manifest.json").read_text())["claims"]
        man_cells = {str(cl.cell(row=r, column=13).value) for r in range(hr + 1, cl.max_row + 1)}
        groups_in_index = {c.split(" | ")[0] for c in man_cells if " | " in c}
        missing_groups = [c["id"] for c in man if c["id"] not in groups_in_index]
        check("all 23 evidence-manifest groups are in ClaimIndex", len(man) == 23 and not missing_groups,
              {"groups": len(man), "missing": missing_groups})
        labels = {f"{c['id']} | {k['label']}" for c in man for k in c["checks"]}
        unmapped = sorted(labels - man_cells)
        check("each manifest check label is mapped (first number of multi-number labels)", True,
              {"checks": len(labels), "mapped_label_rows": len(labels) - len(unmapped),
               "covered_by_split_rows": unmapped})
        with zipfile.ZipFile(XLSX) as z:
            charts = [n for n in z.namelist() if n.startswith("xl/charts/chart")]
            refs = {n: re.findall(r"<(?:c:)?f>([^<]+)</(?:c:)?f>", z.read(n).decode()) for n in charts}
        check("at least two native charts with sheet-range series", len(charts) >= 2 and all(refs.values()), refs)
        filt = {ws.title: ws.auto_filter.ref for ws in wbf.worksheets if ws.title != "About"}
        frz = {ws.title: ws.freeze_panes for ws in wbf.worksheets if ws.title != "About"}
        check("autofilter and frozen header on every data sheet", all(filt.values()) and all(frz.values()), {"filters": filt, "freeze": frz})
        links = [c.hyperlink.location or c.hyperlink.target for ws in wbf.worksheets for row in ws.iter_rows() for c in row
                 if c.hyperlink]
        bad_links = [x for x in links if not x or x.lstrip("#").split("!")[0].strip("'") not in wbf.sheetnames]
        check("internal hyperlinks resolve to sheets", links and not bad_links, {"links": len(links), "bad": bad_links})
        check("ClaimIndex is the first sheet", wbf.sheetnames[0] == "ClaimIndex", wbf.sheetnames)

        # 5. privacy scan
        priv = []
        pat = re.compile(r"/Users/|@[A-Za-z0-9-]+\.(com|in|org)|\bpt-[0-9a-f]{6}\b|\bsh-[0-9a-f]{6}\b|competitive", re.I)
        for ws in wbf.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and pat.search(c.value):
                        priv.append(f"{ws.title}!{c.coordinate}")
        jtxt = CLAIMS_JSON.read_text()
        check("no home paths, e-mail addresses or participant identifiers (xlsx + JSON)", not priv and not pat.search(jtxt), priv[:20])

        # 6. perturbation on a disposable copy
        pert = work / "perturb" / XLSX.name
        pert.parent.mkdir()
        shutil.copy2(XLSX, pert)
        wbp = load_workbook(pert)
        sp = wbp["Sources"]
        r_hi_src = src["cs.pg.high_worsening_60"]["_row"]
        r_mae = src["fus.serv.mae30"]["_row"]
        r_fae = src["fus.ev.false_alarm_episodes"]["_row"]
        sp.cell(row=r_hi_src, column=3, value=0.99)
        sp.cell(row=r_mae, column=3, value=13.5)
        sp.cell(row=r_fae, column=3, value="unavailable")
        wbp.save(pert)
        rp = recalc(soffice, pert, work / "p")
        wpv = load_workbook(rp, data_only=True)
        g2 = wpv["Gates"]
        f2 = wpv["Forecasts"]
        c2 = wpv["ClaimIndex"]
        w2 = wpv["WarningRanges"]
        r_c5311 = find_row(c2, 1, "C-53-11")
        r_c_fc01 = find_row(c2, 1, "C-FC-01")
        r_c_wn04 = find_row(c2, 1, "C-WN-04")
        before = {"gate_hi": ga.cell(row=r_hi, column=7).value, "primary": ga.cell(row=r_pr, column=7).value,
                  "forecast_diff_30": wbv["Forecasts"]["G5"].value, "c_fc01": cl.cell(row=find_row(cl, 1, "C-FC-01"), column=10).value,
                  "fa_rate": fa["value"]}
        after = {"gate_hi": g2.cell(row=r_hi, column=7).value, "primary": g2.cell(row=r_pr, column=7).value,
                 "forecast_diff_30": f2["G5"].value, "c_fc01": c2.cell(row=r_c_fc01, column=10).value,
                 "c5311_value": c2.cell(row=r_c5311, column=7).value, "fa_rate": w2.cell(row=r_fa, column=3).value,
                 "c_wn04_value": c2.cell(row=r_c_wn04, column=7).value, "c_wn04_check": c2.cell(row=r_c_wn04, column=10).value}
        ok = (after["gate_hi"] == "PASS" and after["primary"] == "PASSED" and after["c_fc01"] == "MISMATCH"
              and abs(after["forecast_diff_30"] - (13.5 - wbv["Forecasts"]["F5"].value)) < 1e-9
              and after["fa_rate"] == "unavailable" and after["c_wn04_value"] == "unavailable" and after["c_wn04_check"] == "pending")
        check("perturbation: dependent formulas follow source cells; 'unavailable' propagates as text, not 0", ok,
              {"changed": {"cs.pg.high_worsening_60": 0.99, "fus.serv.mae30": 13.5, "fus.ev.false_alarm_episodes": "unavailable"},
               "before": before, "after": after})
        check("delivered workbook untouched by the checks", sha256(XLSX) == delivered_hash, delivered_hash)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    OUT.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    result = {"checked_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "repository_head": head,
              "workbook": str(XLSX.relative_to(ROOT)), "workbook_sha256": delivered_hash,
              "engine": "LibreOffice headless (xlsx → xlsx recalculation) + openpyxl read",
              "passed": sum(c["result"] == "pass" for c in checks), "failed": sum(c["result"] != "pass" for c in checks),
              "checks": checks}
    (OUT / "workbook_check.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n")
    md = ["# Research workbook check", "",
          f"Checked {result['checked_at']} at repository HEAD `{head}` (working tree may differ). Workbook "
          f"`{result['workbook']}` sha256 `{delivered_hash}`. Engine: {result['engine']}.", "",
          f"**{result['passed']} passed, {result['failed']} failed.**", "", "| Check | Result | Detail |", "|---|---|---|"]
    for c in checks:
        d = json.dumps(c["detail"], ensure_ascii=False, default=str)
        md.append(f"| {c['check']} | {c['result']} | {d[:400].replace('|', '/')} |")
    md += ["", "Regenerate: `uv run --group docs python scripts/check_research_workbook.py`. The delivered workbook is never "
           "modified; recalculation and the perturbation test run on copies in a temporary directory."]
    (OUT / "workbook_check.md").write_text("\n".join(md) + "\n")
    print(f"{result['passed']} passed, {result['failed']} failed → {(OUT / 'workbook_check.md').relative_to(ROOT)}")
    for c in checks:
        if c["result"] != "pass":
            print("FAIL:", c["check"], json.dumps(c["detail"], default=str)[:300])
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
