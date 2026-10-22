"""scripts/verification_ledger.py records real exit codes and parsed totals with explicit statuses."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verification_ledger", ROOT / "scripts" / "verification_ledger.py")
vl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vl)

JUNIT = """<?xml version="1.0"?><testsuites><testsuite name="s" tests="4">
<testcase classname="t.a" name="ok"/>
<testcase classname="t.a" name="bad"><failure message="boom"/></testcase>
<testcase classname="t.b" name="skip1"><skipped message="CGMacros not imported on this machine"/></testcase>
<testcase classname="t.b" name="skip2"><skipped message="CGMacros not imported on this machine"/></testcase>
</testsuite></testsuites>"""


def test_junit_counts_and_grouped_skip_reasons(tmp_path):
    p = tmp_path / "j.xml"
    p.write_text(JUNIT)
    c = vl.parse_junit(p)
    assert (c["total"], c["passed"], c["failed"], c["skipped"]) == (4, 1, 1, 2)
    assert c["skip_reasons"] == {"CGMacros not imported on this machine": 2}
    assert c["failed_cases"] == ["t.a::bad"]
    assert vl.parse_junit(tmp_path / "absent.xml") is None


def test_summary_lines_of_each_tool():
    pw = "\x1b[32m  12 passed\x1b[39m (2.1m)\n  1 skipped\n  2 failed\n  1 flaky\n"
    c = vl.parse_log(pw, "playwright")
    assert (c["passed"], c["failed"], c["skipped"], c["flaky"], c["total"]) == (12, 2, 1, 1, 16)
    v = vl.parse_log(" Test Files  9 passed (9)\n      Tests  41 passed | 2 skipped (43)\n", "vitest")
    assert (v["total"], v["passed"], v["skipped"], v["failed"]) == (43, 41, 2, 0)
    assert vl.parse_log("All checks passed!", "ruff") == {"source": "log", "errors": 0}
    assert vl.parse_log("Found 3 errors.", "ruff")["errors"] == 3
    assert vl.parse_log("nothing here", "playwright") is None


@pytest.mark.parametrize(("code", "counts", "status"), [
    (0, {"total": 3, "passed": 3, "failed": 0, "skipped": 0}, "passed"),
    (1, {"total": 3, "passed": 2, "failed": 1, "skipped": 0}, "failed"),
    (0, {"total": 2, "passed": 0, "failed": 0, "skipped": 2}, "skipped"),  # all skipped is not a pass
    (0, None, "passed"),
    (None, None, "not run"),
])
def test_status_is_explicit(code, counts, status):
    assert vl.derive_status(code, counts) == status


def test_run_records_the_real_exit_code_and_render_lists_it(tmp_path):
    ledger, md = tmp_path / "ledger.json", tmp_path / "LEDGER.md"
    for suite, code in (("ok", 0), ("bad", 3)):
        vl.main(["--repo", str(ROOT), "run", "--ledger", str(ledger), "--suite", suite, "--cwd", str(tmp_path),
                 "--log", str(tmp_path / f"{suite}.log"), "--env", "GT_LEDGER_PROBE=1", "--unset", "PUBLIC_BASE_URL",
                 "--collect",
                 "--", sys.executable, "-c",
                 f"import os,sys; print(os.environ['GT_LEDGER_PROBE'], 'PUBLIC_BASE_URL' in os.environ); sys.exit({code})"])
    vl.main(["--repo", str(ROOT), "add", "--ledger", str(ledger), "--suite", "recorded journeys", "--status", "blocked",
             "--note", "needs data"])
    entries = json.loads(ledger.read_text())["entries"]
    assert [(e["suite"], e["exit_code"], e["status"]) for e in entries] == [
        ("ok", 0, "passed"), ("bad", 3, "failed"), ("recorded journeys", None, "blocked")]
    assert "1 False" in (tmp_path / "ok.log").read_text()  # env set, inherited base URL removed
    assert entries[0]["revision"]["commit"] and entries[0]["env_overrides"]["PUBLIC_BASE_URL"] == "<unset>"
    vl.main(["render", "--ledger", str(ledger), "--out", str(md)])
    text = md.read_text()
    assert "| 2 | bad |" in text and "**failed**" in text and "**blocked**" in text and "needs data" in text


def test_add_rejects_an_unknown_status(tmp_path):
    with pytest.raises(SystemExit):
        vl.main(["add", "--ledger", str(tmp_path / "l.json"), "--suite", "x", "--status", "green"])


def test_tree_digest_ignores_location(tmp_path):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "f.txt").write_text("x")
    assert vl.sha256_tree(tmp_path / "a")["tree_sha256"] == vl.sha256_tree(tmp_path / "b")["tree_sha256"]


def test_saved_evidence_carries_no_home_directory_or_host_name(tmp_path):
    home = str(Path.home())
    f = tmp_path / "j.xml"
    f.write_text(f'<testsuite hostname="my-laptop.local"><testcase file="{home}/x.py"/></testsuite>'
                 '<testsuite hostname="chromium"/>')
    vl.main(["scrub", "--dir", str(tmp_path)])
    text = f.read_text()
    assert home not in text and "my-laptop" not in text and 'hostname="chromium"' in text


def _git_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True)
    (repo / "tracked.py").write_text("a = 1\n")
    (repo / ".gitignore").write_text("ignored/\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def test_revision_keeps_the_first_dirty_path_whole_and_counts_untracked_sources(tmp_path):
    repo = _git_repo(tmp_path)
    clean = vl.git_revision(repo)
    assert clean["dirty"] is False and clean["dirty_files"] == [] and clean["untracked_files"] == {}
    # an untracked, not-ignored runner is part of what was tested: dirty, with its digest
    (repo / "runner.py").write_text("print(1)\n")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "out.bin").write_text("x")
    (repo / "evidence").mkdir()
    (repo / "evidence" / "log.txt").write_text("x")
    r = vl.git_revision(repo, [repo / "evidence"])
    assert r["dirty"] is True and list(r["untracked_files"]) == ["runner.py"]
    assert r["untracked_files"]["runner.py"] == vl.sha256_file(repo / "runner.py") and r["untracked_sha256"]
    # a modified tracked file keeps its full name (porcelain's leading status space is not trimmed away)
    (repo / "tracked.py").write_text("a = 2\n")
    r = vl.git_revision(repo, [repo / "evidence"])
    assert r["dirty_files"] == ["tracked.py"] and r["uncommitted_diff_sha256"]


def test_failed_command_without_junit_does_not_inherit_stale_totals(tmp_path):
    ledger, junit = tmp_path / "l.json", tmp_path / "j.xml"
    junit.write_text('<testsuite><testcase classname="old" name="passing"/></testsuite>')
    code = vl.main(["--repo", str(ROOT), "run", "--ledger", str(ledger), "--suite", "s", "--cwd", str(tmp_path),
                    "--log", str(tmp_path / "s.log"), "--junit", str(junit), "--", sys.executable, "-c",
                    "import sys; sys.exit(3)"])
    e = json.loads(ledger.read_text())["entries"][0]
    assert code == 3 and e["exit_code"] == 3 and e["status"] == "failed"
    assert e["counts"] is None and e["stale_junit_removed"] is True and e["junit_written"] is False


def test_cli_returns_the_suite_exit_code_unless_collecting(tmp_path):
    def run(*extra):
        return vl.main(["--repo", str(ROOT), "run", "--ledger", str(tmp_path / "l.json"), "--suite", "s",
                        "--cwd", str(tmp_path), "--log", str(tmp_path / "s.log"), *extra, "--", sys.executable, "-c",
                        "import sys; sys.exit(2)"])
    assert run() == 2
    assert run("--collect") == 0
    assert [e["status"] for e in json.loads((tmp_path / "l.json").read_text())["entries"]] == ["failed", "failed"]
