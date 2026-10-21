"""Verification ledger: run checks with captured exit codes and record them in a machine-readable ledger.

Each entry records the suite, exact command, working directory, start/end times, the real exit code (no shell piping
in between), passed/failed/skipped totals parsed from JUnit XML or the tool's own summary line, skip reasons, the
tested git revision (commit, tree hash, dirty flag and a digest of any uncommitted tracked diff) and the log location.
Snapshots record dependency versions and sha256 hashes of the serving registry, model and evidence files, so the
hashes before and after a verification run can be compared. ``render`` writes a markdown summary table.

Statuses are explicit: passed, failed, skipped, blocked, not run. A zero exit code with no executed test and at least
one skip is ``skipped``, not ``passed``; a nonzero exit code is ``failed`` unless an explicit status is given.

Usage (from the repository root):
  uv run python scripts/verification_ledger.py snapshot --ledger L.json --label before [--artifact-root DIR]
  uv run python scripts/verification_ledger.py run --ledger L.json --suite pytest --cwd . --log out/pytest.log \
      --junit out/pytest.xml -- uv run pytest -q --junitxml=out/pytest.xml
  uv run python scripts/verification_ledger.py add --ledger L.json --suite X --status blocked --note "reason"
  uv run python scripts/verification_ledger.py render --ledger L.json --out LEDGER.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30), "IST")
STATUSES = ("passed", "failed", "skipped", "blocked", "not run")
SERVING_EXPERIMENT = "gt-primary-2026-10-13-fusion"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# ------------------------------------------------------------------------------------------------ helpers

def now() -> dict[str, str]:
    t = datetime.now(UTC)
    return {"utc": t.isoformat(timespec="seconds"), "ist": t.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(directory: Path) -> dict[str, Any]:
    """Per-file sha256 plus one digest over the sorted ``relative path, file digest`` lines (stable across copies)."""
    files = {p.relative_to(directory).as_posix(): sha256_file(p)
             for p in sorted(directory.rglob("*")) if p.is_file() and p.name != ".DS_Store"}
    tree = hashlib.sha256("".join(f"{k}\0{v}\n" for k, v in files.items()).encode()).hexdigest()
    return {"tree_sha256": tree, "files": files}


def _out(cmd: list[str], cwd: Path | None = None) -> str | None:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return (r.stdout or r.stderr).strip() if r.returncode == 0 else None


def git_revision(repo: Path) -> dict[str, Any]:
    """Commit, tree hash, branch, dirty flag (tracked files) and the sha256 of the uncommitted tracked diff."""
    commit = _out(["git", "rev-parse", "HEAD"], repo)
    dirty_names = _out(["git", "status", "--porcelain", "--untracked-files=no"], repo) or ""
    diff = subprocess.run(["git", "diff", "HEAD", "--binary"], cwd=repo, capture_output=True, check=False).stdout
    return {
        "commit": commit, "tree": _out(["git", "rev-parse", "HEAD^{tree}"], repo),
        "branch": _out(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo),
        "worktree": str(repo.resolve()), "dirty": bool(dirty_names.strip()),
        "dirty_files": [ln[3:] for ln in dirty_names.splitlines() if ln.strip()],
        "uncommitted_diff_sha256": hashlib.sha256(diff).hexdigest() if diff else None,
    }


def dependency_versions(repo: Path) -> dict[str, str | None]:
    py = ("import sys, importlib.metadata as m\n"
          "out = {'python': sys.version.split()[0]}\n"
          "for p in ('lightgbm','numpy','pandas','scikit-learn','fastapi','pytest','ruff','catboost','pyarrow'):\n"
          "    try: out[p] = m.version(p)\n"
          "    except m.PackageNotFoundError: out[p] = None\n"
          "import json; print(json.dumps(out))")
    raw = _out(["uv", "run", "--frozen", "python", "-c", py], repo)
    versions: dict[str, str | None] = json.loads(raw.splitlines()[-1]) if raw else {"python": None}
    web = repo / "apps" / "web"
    versions["uv"] = _out(["uv", "--version"])
    versions["node"] = _out(["node", "--version"])
    versions["npm"] = _out(["npm", "--version"])
    for pkg in ("@playwright/test", "typescript", "vitest", "vite", "react"):
        pj = web / "node_modules" / pkg / "package.json"
        versions[pkg] = json.loads(pj.read_text())["version"] if pj.exists() else None
    return versions


def artifact_hashes(root: Path) -> dict[str, Any]:
    """Hashes of the serving registry, the serving model directory and the incumbent's evidence files under ``root``."""
    out: dict[str, Any] = {"artifact_root": str(root.resolve())}
    reg_path = root / "artifacts" / "registry.json"
    if not reg_path.exists():
        out["registry"] = None
        return out
    reg = json.loads(reg_path.read_text())
    out["registry"] = {"path": "artifacts/registry.json", "sha256": sha256_file(reg_path), "serving": reg.get("serving")}
    serving = (reg.get("serving") or {}).get("dataset_replay")
    entry = next((m for m in reg.get("models", []) if m.get("model_version") == serving), None)
    if entry is not None:
        mdir = root / entry["artifact_dir"]
        out["serving_model_dir"] = ({"path": entry["artifact_dir"], **sha256_tree(mdir)} if mdir.is_dir()
                                    else {"path": entry["artifact_dir"], "missing": True})
    files = [f"artifacts/experiments/{SERVING_EXPERIMENT}/metrics.json",
             f"artifacts/experiments/{SERVING_EXPERIMENT}/predictions.parquet",
             "reports/serving_parity.json", "reports/serving_parity.md"]
    out["files"] = {f: (sha256_file(root / f) if (root / f).exists() else None) for f in files}
    return out


# ------------------------------------------------------------------------------------------------ result parsing

def parse_junit(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    passed = failed = skipped = 0
    reasons: dict[str, int] = {}
    failures: list[str] = []
    for c in cases:
        name = f"{c.get('classname', '')}::{c.get('name', '')}"
        if c.find("failure") is not None or c.find("error") is not None:
            failed += 1
            failures.append(name)
        elif c.find("skipped") is not None:
            skipped += 1
            s = c.find("skipped")
            msg = (s.get("message") or (s.text or "")).strip() or "no reason given"
            reasons[msg] = reasons.get(msg, 0) + 1
        else:
            passed += 1
    return {"source": "junit", "total": len(cases), "passed": passed, "failed": failed, "skipped": skipped,
            "skip_reasons": reasons, "failed_cases": failures}


def parse_log(text: str, kind: str) -> dict[str, Any] | None:
    """Summary-line parsing for tools run without a JUnit file (ruff, vitest, playwright list, tsc, vite build)."""
    t = ANSI.sub("", text)
    if kind == "ruff":
        if "All checks passed" in t:
            return {"source": "log", "errors": 0}
        m = re.search(r"Found (\d+) error", t)
        return {"source": "log", "errors": int(m.group(1))} if m else None
    if kind == "vitest":
        m = re.search(r"^\s*Tests\s+(.+?)\s*\((\d+)\)\s*$", t, re.M)
        if not m:
            return None
        c = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|todo)", m.group(1))}
        return {"source": "log", "total": int(m.group(2)), "passed": c.get("passed", 0), "failed": c.get("failed", 0),
                "skipped": c.get("skipped", 0) + c.get("todo", 0), "skip_reasons": {}}
    if kind == "playwright":
        c = {k: int(v) for v, k in re.findall(r"^\s+(\d+) (passed|failed|skipped|flaky|did not run|interrupted)",
                                               t, re.M)}
        if not c:
            return None
        return {"source": "log", "total": sum(c.values()), "passed": c.get("passed", 0),
                "failed": c.get("failed", 0) + c.get("interrupted", 0), "skipped": c.get("skipped", 0),
                "flaky": c.get("flaky", 0), "did_not_run": c.get("did not run", 0), "skip_reasons": {}}
    return None


def derive_status(exit_code: int | None, counts: dict[str, Any] | None) -> str:
    if exit_code is None:
        return "not run"
    if exit_code != 0:
        return "failed"
    if counts and counts.get("total") and counts.get("passed", 0) == 0 and counts.get("failed", 0) == 0 \
            and counts.get("skipped", 0) > 0:
        return "skipped"
    return "passed"


# ------------------------------------------------------------------------------------------------ ledger I/O

def load(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {"ledger_format": "glucotwin-verification-ledger-1", "created": now(), "snapshots": [], "entries": []}


def save(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)


def rel(p: Path | str | None, base: Path) -> str | None:
    if p is None:
        return None
    p = Path(p).resolve()
    try:
        return p.relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(p)


def cmd_snapshot(a: argparse.Namespace) -> int:
    repo = Path(a.repo).resolve()
    ledger_path = Path(a.ledger)
    ledger = load(ledger_path)
    snap = {"label": a.label, "at": now(), "revision": git_revision(repo), "versions": dependency_versions(repo),
            "artifacts": artifact_hashes(Path(a.artifact_root).resolve() if a.artifact_root else repo)}
    if a.artifact_root and Path(a.artifact_root).resolve() != repo:
        snap["artifacts_in_worktree"] = artifact_hashes(repo)
    ledger["snapshots"].append(snap)
    save(ledger_path, ledger)
    print(json.dumps({k: snap[k] for k in ("label", "at", "revision")}, indent=1))
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    repo = Path(a.repo).resolve()
    ledger_path = Path(a.ledger)
    cmd = a.command[1:] if a.command and a.command[0] == "--" else a.command
    if not cmd:
        sys.exit("run: give the command after --")
    cwd = Path(a.cwd).resolve()
    log = Path(a.log).resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for k in a.unset or []:
        env.pop(k, None)
    for kv in a.env or []:
        k, _, v = kv.partition("=")
        env[k] = v
    rev = git_revision(repo)
    start = now()
    with open(log, "wb") as fh:
        fh.write(f"$ (cd {cwd} && {' '.join(cmd)})\n".encode())
        proc = subprocess.run(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, check=False)
    end = now()
    text = log.read_text(errors="replace")
    counts = parse_junit(Path(a.junit)) if a.junit else None
    if counts is None:
        counts = parse_log(text, a.kind)
    status = a.status or derive_status(proc.returncode, counts)
    entry = {
        "suite": a.suite, "command": " ".join(cmd), "cwd": rel(cwd, repo), "start": start, "end": end,
        "exit_code": proc.returncode, "status": status, "counts": counts,
        "env_overrides": {**{kv.partition("=")[0]: kv.partition("=")[2] for kv in a.env or []},
                          **{k: "<unset>" for k in a.unset or []}},
        "log": rel(log, repo), "junit": rel(a.junit, repo) if a.junit else None,
        "revision": rev, "note": a.note,
    }
    ledger = load(ledger_path)
    ledger["entries"].append(entry)
    save(ledger_path, ledger)
    tail = "\n".join(ANSI.sub("", text).strip().splitlines()[-4:])
    print(f"[{status}] {a.suite}: exit {proc.returncode}; {json.dumps(counts) if counts else 'no counts'}\n{tail}")
    return 0


def cmd_add(a: argparse.Namespace) -> int:
    repo = Path(a.repo).resolve()
    if a.status not in STATUSES:
        sys.exit(f"status must be one of {STATUSES}")
    ledger_path = Path(a.ledger)
    ledger = load(ledger_path)
    counts = json.loads(a.counts) if a.counts else None
    ledger["entries"].append({
        "suite": a.suite, "command": a.cmd, "cwd": a.cwd, "start": now(), "end": None,
        "exit_code": a.exit_code, "status": a.status, "counts": counts, "env_overrides": {},
        "log": a.log, "junit": None, "revision": git_revision(repo), "note": a.note,
    })
    save(ledger_path, ledger)
    return 0


def _counts_cell(c: dict[str, Any] | None) -> tuple[str, str, str]:
    if not c:
        return "–", "–", "–"
    if "errors" in c:
        return ("0 lint errors" if c["errors"] == 0 else "–"), (str(c["errors"]) if c["errors"] else "0"), "–"
    return str(c.get("passed", "–")), str(c.get("failed", "–")), str(c.get("skipped", "–"))


def cmd_render(a: argparse.Namespace) -> int:
    ledger = load(Path(a.ledger))
    lines = [f"# {a.title}", "",
             "Generated by `scripts/verification_ledger.py render` from the machine-readable ledger "
             f"`{Path(a.ledger).name}`. Statuses: passed, failed, skipped, blocked, not run.", ""]
    for s in ledger.get("snapshots", []):
        r, art = s["revision"], s.get("artifacts", {})
        lines += [f"## Snapshot `{s['label']}` — {s['at']['ist']}", "",
                  f"- Revision: `{(r.get('commit') or '')[:12]}` on `{r.get('branch')}`, tree `{(r.get('tree') or '')[:12]}`, "
                  f"{'dirty: ' + ', '.join(r['dirty_files']) if r.get('dirty') else 'clean tracked tree'}",
                  "- Versions: " + ", ".join(f"{k} {v}" for k, v in s.get("versions", {}).items() if v)]
        if art.get("registry"):
            lines.append(f"- `artifacts/registry.json` sha256 `{art['registry']['sha256']}`; serving "
                         f"`{(art['registry'].get('serving') or {}).get('dataset_replay')}`")
        md = art.get("serving_model_dir")
        if md and not md.get("missing"):
            lines.append(f"- Serving model dir `{md['path']}` tree sha256 `{md['tree_sha256']}` "
                         f"({len(md['files'])} files)")
        for f, h in (art.get("files") or {}).items():
            lines.append(f"- `{f}` sha256 `{h}`")
        if s.get("artifacts_in_worktree"):
            same = s["artifacts_in_worktree"].get("files") == art.get("files") and \
                (s["artifacts_in_worktree"].get("serving_model_dir") or {}).get("tree_sha256") == (md or {}).get("tree_sha256") \
                and (s["artifacts_in_worktree"].get("registry") or {}).get("sha256") == (art.get("registry") or {}).get("sha256")
            lines.append(f"- Worktree copies identical to `{art.get('artifact_root')}`: **{'yes' if same else 'NO'}**")
        lines.append("")
    lines += ["## Checks", "",
              "| # | Suite | Command (cwd) | Revision | Start → end (IST) | Exit | Status | Passed | Failed | Skipped | Notes |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, e in enumerate(ledger.get("entries", []), 1):
        p, f, s = _counts_cell(e.get("counts"))
        r = e.get("revision") or {}
        rev = f"`{(r.get('commit') or '')[:7]}`" + (" (dirty)" if r.get("dirty") else "")
        st = (e.get("start") or {}).get("ist", "")[11:19]
        en = ((e.get("end") or {}).get("ist") or "")[11:19]
        notes = []
        if e.get("note"):
            notes.append(e["note"])
        c = e.get("counts") or {}
        if c.get("skip_reasons"):
            notes.append("skips: " + "; ".join(f"{n}× {m[:90]}" for m, n in c["skip_reasons"].items()))
        if c.get("failed_cases"):
            notes.append("failed: " + ", ".join(c["failed_cases"][:5]))
        if e.get("log"):
            notes.append(f"log `{e['log']}`")
        cmd = f"`{e.get('command')}` ({e.get('cwd')})".replace("|", "\\|")
        lines.append(f"| {i} | {e['suite']} | {cmd} | {rev} | {st} → {en} | {e.get('exit_code', '–')} | "
                     f"**{e['status']}** | {p} | {f} | {s} | {'<br>'.join(notes).replace('|', '/')} |")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"wrote {a.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(ROOT), help="git worktree whose revision is recorded (default: this repo)")
    sub = ap.add_subparsers(dest="cmd_name", required=True)

    s = sub.add_parser("snapshot", help="record dependency versions and artifact hashes")
    s.add_argument("--ledger", required=True)
    s.add_argument("--label", required=True)
    s.add_argument("--artifact-root", help="checkout whose artifacts/ and reports/ are hashed (default: --repo)")
    s.set_defaults(fn=cmd_snapshot)

    r = sub.add_parser("run", help="run a command, capture its exit code and append an entry")
    r.add_argument("--ledger", required=True)
    r.add_argument("--suite", required=True)
    r.add_argument("--cwd", default=".")
    r.add_argument("--log", required=True)
    r.add_argument("--junit", help="JUnit XML written by the command (preferred source of counts)")
    r.add_argument("--kind", default="generic", choices=["generic", "ruff", "vitest", "playwright"])
    r.add_argument("--env", action="append", help="KEY=VALUE set for the command")
    r.add_argument("--unset", action="append", help="environment variable removed for the command")
    r.add_argument("--status", choices=STATUSES, help="override the derived status (state why in --note)")
    r.add_argument("--note")
    r.add_argument("command", nargs=argparse.REMAINDER)
    r.set_defaults(fn=cmd_run)

    d = sub.add_parser("add", help="append a manual entry (blocked / not run / environment skip)")
    d.add_argument("--ledger", required=True)
    d.add_argument("--suite", required=True)
    d.add_argument("--status", required=True)
    d.add_argument("--cmd")
    d.add_argument("--cwd")
    d.add_argument("--exit-code", type=int)
    d.add_argument("--counts", help="JSON object, e.g. '{\"passed\": 1, \"failed\": 0, \"skipped\": 0}'")
    d.add_argument("--log")
    d.add_argument("--note")
    d.set_defaults(fn=cmd_add)

    m = sub.add_parser("render", help="write the markdown summary")
    m.add_argument("--ledger", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--title", default="Verification ledger")
    m.set_defaults(fn=cmd_render)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
