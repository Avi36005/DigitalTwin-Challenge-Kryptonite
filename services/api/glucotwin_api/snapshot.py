"""Published evidence snapshot for the public synthetic demonstration (``reports/public_evidence/``).

A hosted copy has no git-ignored experiment artifacts, so its evidence pages would read "not run". ``export`` records
what this API returns *in public mode* (pooled results only, per-participant rows already withheld) for every evidence
endpoint, refuses to write anything that still names or lists a participant, and stamps a manifest. In public mode only,
an evidence endpoint whose saved artifacts are missing serves the matching file, marked ``source: published_snapshot``.
A local installation never reads the snapshot.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from glucotwin.config import paths

MARKS = ("source", "snapshot_exported_at", "snapshot_commit")
PSEUDONYM = re.compile(r"\bpt-[0-9a-f]{6}\b|\bCGMacros-\d+\b", re.IGNORECASE)
ID_KEYS = {"patient_id", "participant_id", "display_alias", "pseudonym", "pseudonymous_id", "participants_list"}
ROW_KEYS = ("per_patient", "per_participant")


class SnapshotLeak(ValueError):
    """The export would publish a participant identifier or per-participant rows."""


def directory() -> Path:
    return paths().reports / "public_evidence"


def file_name(endpoint: str, item: str | None = None) -> str:
    return f"{endpoint}__{item}.json" if item else f"{endpoint}.json"


def load(name: str, base: Path | None = None) -> dict[str, Any] | None:
    """A snapshot response, marked with its provenance; None when the snapshot or this file is absent."""
    d = base or directory()
    f, m = d / name, d / "manifest.json"
    if not (f.is_file() and m.is_file()):
        return None
    man = json.loads(m.read_text())
    return {**json.loads(f.read_text()), "source": "published_snapshot",
            "snapshot_exported_at": man["exported_at"], "snapshot_commit": man["commit"]}


def withhold_ids(obj: Any) -> Any:
    """Public demo: a list made only of pseudonymous participant IDs (e.g. a fold's calibration participants) becomes its
    count, so pooled evidence keeps its sizes without naming anyone. Everything else is returned unchanged."""
    if isinstance(obj, dict):
        return {k: withhold_ids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if obj and all(isinstance(x, str) and PSEUDONYM.fullmatch(x) for x in obj):
            return len(obj)
        return [withhold_ids(v) for v in obj]
    return obj


def check_aggregate(obj: Any, where: str = "$") -> None:
    """Raise SnapshotLeak if ``obj`` holds a pseudonymous participant ID, an ID-valued key or per-participant rows."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k)
            if PSEUDONYM.search(key):
                raise SnapshotLeak(f"{where}: key {key!r} looks like a participant identifier")
            low = key.lower()
            if low in ID_KEYS and v not in (None, "", [], {}):
                raise SnapshotLeak(f"{where}.{key}: participant identifier field has a value")
            if low.startswith(ROW_KEYS) and isinstance(v, (list, dict)) and v:  # a scalar (e.g. min over people) is pooled
                raise SnapshotLeak(f"{where}.{key}: per-participant rows present")
            check_aggregate(v, f"{where}.{key}")
    elif isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj) and any("participant" in x or "patient_id" in x for x in obj):
            raise SnapshotLeak(f"{where}: list of per-participant rows")
        for i, v in enumerate(obj):
            check_aggregate(v, f"{where}[{i}]")
    elif isinstance(obj, str) and PSEUDONYM.search(obj):
        raise SnapshotLeak(f"{where}: value {obj[:60]!r} contains a participant identifier")


def _commit() -> str:
    try:
        root = paths().root
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def export(out: Path | None = None) -> dict[str, Any]:
    """Write the snapshot from this machine's saved artifacts, through the API in public mode. Returns the manifest."""
    from fastapi.testclient import TestClient

    out = out or directory()
    keep = {k: os.environ.get(k) for k in ("GLUCOTWIN_PUBLIC_DEMO", "GLUCOTWIN_VAR_DIR", "GLUCOTWIN_WEB_DIST")}
    files: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="glucotwin-snapshot-") as var:
        os.environ.update({"GLUCOTWIN_PUBLIC_DEMO": "1", "GLUCOTWIN_VAR_DIR": var})
        os.environ.pop("GLUCOTWIN_WEB_DIST", None)
        try:
            from .app import create_app

            client = TestClient(create_app())

            def get(path: str) -> dict[str, Any]:
                r = client.get(f"/api/v1{path}")
                if r.status_code != 200:
                    raise RuntimeError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
                body = r.json()
                if body.get("source") == "published_snapshot":
                    raise RuntimeError(f"{path}: served from the snapshot itself; export needs the saved artifacts")
                return {k: v for k, v in body.items() if k not in MARKS}

            listing = get("/evaluations")
            if not any(i["status"] == "completed" for i in listing["items"]):
                raise RuntimeError("No completed evaluation on this machine; nothing to publish.")
            files[file_name("evaluations")] = listing
            latest = get("/evaluations/latest")
            if latest.get("status") != "completed":
                raise RuntimeError("/evaluations/latest is not completed; nothing to publish.")
            files[file_name("evaluations", "latest")] = latest
            for item in listing["items"]:
                eid = item["experiment_id"]
                if item["regime"] == "nested_research":
                    if item["status"] == "completed":
                        files[file_name("research", eid)] = get(f"/research/{eid}")
                elif item["status"] == "completed":
                    files[file_name("evaluations", eid)] = get(f"/evaluations/{eid}")
            files[file_name("research_summaries")] = get("/research-summaries")
            files[file_name("datasets")] = get("/datasets")
        finally:
            for k, v in keep.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    for name, body in files.items():
        check_aggregate(body, name)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    for name, body in files.items():
        (out / name).write_text(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    manifest = {
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": _commit(),
        "note": "Aggregate-only copy of what the API returns in public demonstration mode, served there only when the "
                "saved experiment artifacts are absent. No participant identifiers or per-participant rows.",
        "experiments": sorted({i["experiment_id"] for i in files[file_name("evaluations")]["items"]
                               if i["status"] == "completed"}),
        "files": sorted(files),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest
