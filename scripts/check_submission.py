"""Check the README submission links and write docs/submission_access_audit.md.

Local checks (always): every README link/image target exists, is not Git-ignored (so it will be in the public
repository), in-page anchors resolve to README headings, PDFs/PPTX open and report a page/slide count, the twelve
form sections are present, and the links in the team folder index (`Team Name_College Name`, e.g. Kryptonite_VESIT/)
resolve. With --online, external http(s) links are fetched (read-only GET). Publication-dependent
checks (public visibility, signed-out access, YouTube) are listed as pending until their URLs exist in
configs/submission.yaml — this script never publishes or uploads anything.

Usage:  uv run python scripts/check_submission.py [--online]
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
OUT = ROOT / "docs/submission_access_audit.md"
SECTIONS = ["Team details", "College or incubator information", "Project title", "Problem statement",
            "Healthcare use case", "Technical stack", "AI and ML model details", "Demo video",
            "Open-source license", "Architecture diagram", "Presentation", "Accessible files and links"]
LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")


def slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def describe_file(path: Path) -> str:
    if path.is_dir():
        return "directory"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True)
        m = re.search(r"Pages:\s+(\d+)", out.stdout)
        pages = m.group(1) if m else str(len(re.findall(rb"/Type\s*/Page[^s]", path.read_bytes())))
        return f"PDF, {pages} pages, {path.stat().st_size / 1e6:.1f} MB"
    if suffix == ".pptx":
        with zipfile.ZipFile(path) as z:
            n = sum(1 for f in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", f))
        return f"PPTX, {n} slides, {path.stat().st_size / 1e6:.1f} MB"
    if suffix == ".png":
        ok = path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        return "PNG image" if ok else "INVALID PNG"
    return f"{suffix.lstrip('.') or 'file'}, {path.stat().st_size / 1e3:.0f} kB"


def check_local(target: str, anchors: set[str], base: Path = README.parent) -> tuple[bool, str]:
    path_part, _, frag = target.partition("#")
    if not path_part:
        return (frag in anchors, "anchor found" if frag in anchors else f"MISSING anchor #{frag}")
    path = (base / path_part).resolve()
    if not path.exists():
        return False, "MISSING file"
    if frag and path == README and frag not in anchors:
        return False, f"MISSING README anchor #{frag}"
    rel = path.relative_to(ROOT).as_posix()
    if git("check-ignore", "-q", rel).returncode == 0:
        return False, "file exists but is Git-ignored (would not be published)"
    tracked = git("ls-files", "--error-unmatch", rel).returncode == 0
    desc = describe_file(path)
    return ("INVALID" not in desc), f"{desc}; {'tracked by Git' if tracked else 'not ignored, not yet committed'}"


def check_online(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "glucotwin-link-check/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return True, f"HTTP {r.status} (signed-out request, final URL {r.geturl()[:70]})"
    except Exception as exc:  # noqa: BLE001 — report any failure as a result, not a crash
        return False, f"request failed: {exc}"[:120]


def main() -> int:
    online = "--online" in sys.argv
    text = README.read_text()
    headings = [h for h in re.findall(r"^#{1,6} (.+)$", text, flags=re.M)]
    anchors = {slug(h) for h in headings}
    sec_rows = []
    for i, name in enumerate(SECTIONS, start=1):
        ok = any(h.strip() == f"{i}. {name}" for h in headings)
        sec_rows.append((i, name, ok))
    links, seen = [], set()
    for bang, label, target in LINK.findall(text):
        if target in seen:
            continue
        seen.add(target)
        kind = "image" if bang else "link"
        if target.startswith(("http://", "https://")):
            if online:
                ok, res = check_online(target)
            else:
                ok, res = True, "external — not fetched (run with --online)"
        else:
            ok, res = check_local(target, anchors)
        links.append((kind, label or "(image)", target, ok, res))
    sub = yaml.safe_load((ROOT / "configs/submission.yaml").read_text())
    index = ROOT / f"{sub['team']['name']}_{sub['team']['institution_short']}" / "README.md"
    if not index.exists():
        links.append(("folder", "team folder index", index.relative_to(ROOT).as_posix(), False,
                      "MISSING — run scripts/build_submission_assets.py"))
    for target in dict.fromkeys(t for _, _, t in (LINK.findall(index.read_text()) if index.exists() else [])):
        if target.startswith(("http://", "https://")):
            ok, res = check_online(target) if online else (True, "external — not fetched (run with --online)")
        else:
            ok, res = check_local(target, anchors, index.parent)
        links.append(("folder link", index.parent.name, target, ok, res))
    today = date.today().isoformat()
    bad = [x for x in links if not x[3]] + [x for x in sec_rows if not x[2]]

    out = [
        "# Submission access audit",
        "",
        f"Generated by `scripts/check_submission.py{' --online' if online else ''}` on **{today}**. Re-run after any README "
        "change and again after publication. “Accessible without additional permissions” is claimed only for checks "
        "marked passed below; publication-dependent checks stay pending until they are actually performed.",
        "",
        "## Mandatory README sections (form items 1–12)",
        "",
        "| # | Section heading | Present |",
        "|---|---|---|",
        *[f"| {i} | {n} | {'yes' if ok else '**NO**'} |" for i, n, ok in sec_rows],
        "",
        "## README and team folder links",
        "",
        "| Type | Text | Target | Result | Check |",
        "|---|---|---|---|---|",
        *[f"| {k} | {lbl.replace('|', '/')} | `{t}` | {'passed' if ok else '**FAILED**'} | {r} |" for k, lbl, t, ok, r in links],
        "",
        "## Publication-dependent checks",
        "",
        "| Check | Intended target | Status |",
        "|---|---|---|",
        f"| Repository is public and opens signed out | {sub['links']['repository'] or 'public GitHub URL (not yet created)'} | "
        f"{'URL recorded — verify signed out' if sub['links']['repository'] else 'Pending — repository not yet published (requires team authorization)'} |",
        "| README links resolve on GitHub (relative paths, PDF/PPTX open or download without sign-in) | files above | "
        "Pending — same files pass locally; recheck on the published repository |",
        f"| Demo video plays signed out, visibility **Unlisted** | {sub['links']['video'] or 'unlisted YouTube URL (not yet uploaded)'} | "
        f"{'URL recorded — verify playback and visibility' if sub['links']['video'] else 'Pending — video not yet recorded or uploaded'} |",
        f"| YouTube-displayed duration at least {sub['video']['minimum_duration']} (target {sub['video']['target_duration']}) | — | "
        f"{sub['video']['youtube_displayed_duration'] or 'Pending'} |",
        f"| Rendered video duration | — | {sub['video']['rendered_duration'] or 'Pending — not yet recorded'} |",
        "| Unstop form: repository URL field (≤ 500 characters, direct GitHub URL) | — | Pending — team leader submits |",
        "",
        f"**Summary:** {len(links) - sum(1 for x in links if not x[3])}/{len(links)} README links and images pass the local "
        f"checks (including the team folder index); {sum(1 for x in sec_rows if x[2])}/12 mandatory sections present. "
        + ("No local failures." if not bad else f"{len(bad)} local failure(s) — fix before submission."),
        "",
    ]
    OUT.write_text("\n".join(out))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(links)} links, {len(bad)} failure(s)")
    for x in bad:
        print("  FAILED:", x)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
