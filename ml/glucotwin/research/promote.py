"""Explicit promotion / rollback of a frozen research candidate (separate from training; never run implicitly).

``promote`` without ``confirm=True`` is a dry run that only verifies the candidate. With confirmation it copies the
checksum-verified bundle to ``artifacts/models/<model_version>``, updates the registry ATOMICALLY (write + rename) and
verifies that the registry now resolves to a loadable, matching artifact; on failure the previous registry is restored.
Existing replay sessions keep the engine they were created with; issued forecasts are never reinterpreted (they carry
their model version in the audit database). A restarted API serves new sessions with the promoted model.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from glucotwin.config import file_sha256, fingerprint, paths
from glucotwin.models.population import ArtifactError, PopulationBundle
from glucotwin.research.protocol import research_dir


class PromotionError(RuntimeError):
    pass


def _registry_path(path: str | Path | None) -> Path:
    return Path(path) if path else paths().artifacts / "registry.json"


def verify_candidate(directory: Path) -> dict[str, Any]:
    cand = json.loads((directory / "candidate.json").read_text())
    for name, digest in cand["files_sha256"].items():
        if file_sha256(directory / name) != digest:
            raise PromotionError(f"{name} differs from the packaged checksum")
    try:
        bundle = PopulationBundle.load(directory)
    except ArtifactError as exc:
        raise PromotionError(str(exc)) from exc
    serving = json.loads((directory / "serving.json").read_text())
    if serving["model_version"] != cand["model_version"]:
        raise PromotionError("serving.json and candidate.json disagree on the model version")
    for key in ("adaptation", "intervals", "alerts", "event_definition"):
        if key not in serving:
            raise PromotionError(f"candidate lacks its {key} policy; a promoted pipeline must bundle it")
    return {"candidate": cand, "serving": serving, "horizons": bundle.horizons, "family": bundle.family}


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _resolves(reg_path: Path, version: str) -> None:
    reg = json.loads(reg_path.read_text())
    if reg.get("serving", {}).get("dataset_replay") != version:
        raise PromotionError("registry does not point at the requested version")
    entry = next(m for m in reg["models"] if m["model_version"] == version)
    d = paths().root / entry["artifact_dir"]
    PopulationBundle.load(d)
    if json.loads((d / "serving.json").read_text())["model_version"] != version:
        raise PromotionError("artifact serving.json does not match the registry entry")


def promote(experiment_id: str, track: str, registry: str | None = None, confirm: bool = False) -> dict[str, Any]:
    src = research_dir(experiment_id) / "candidates" / track
    if not (src / "candidate.json").exists():
        raise PromotionError(f"No packaged candidate for {track}; run the research assessment first")
    info = verify_candidate(src)
    cand, serving = info["candidate"], info["serving"]
    if not cand["serving_eligible"]:
        raise PromotionError(f"Track {track} is not serving-eligible (the replay app streams 5-minute data)")
    version = cand["model_version"]
    reg_path = _registry_path(registry)
    if not confirm:
        return {"status": "dry_run", "model_version": version, "verified": True,
                "would_update": str(reg_path), "confirm_with": f"glucotwin research promote --track {track} --yes"}
    dest = paths().artifacts / "models" / version
    if dest.exists():
        verify_candidate(dest) if (dest / "candidate.json").exists() else None
    else:
        shutil.copytree(src, dest)
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {"models": [], "serving": {}}
    backup = json.loads(json.dumps(reg))
    previous = reg.get("serving", {}).get("dataset_replay")
    reg["models"] = [m for m in reg["models"] if m["model_version"] != version]
    man = json.loads((dest / "manifest.json").read_text())
    reg["models"].append({
        "model_version": version, "model_family": serving["model_family"], "feature_set_id": serving["feature_set_id"],
        "horizons": man["horizons"], "artifact_dir": str(dest.relative_to(paths().root)),
        "artifact_checksum": fingerprint(man["files"]), "selection_rationale": serving["selection_rationale"],
        "evaluation_reference": f"artifacts/research/{experiment_id}/report.json", "mode": "dataset_replay",
        "synthetic_fitted": False,
    })
    reg.setdefault("serving", {})["dataset_replay"] = version
    reg.setdefault("history", []).append({"at": datetime.now(UTC).isoformat(timespec="seconds"), "action": "promote",
                                          "from": previous, "to": version, "experiment_id": experiment_id})
    _atomic_write(reg_path, reg)
    try:
        _resolves(reg_path, version)
    except Exception:
        _atomic_write(reg_path, backup)
        raise
    return {"status": "promoted", "model_version": version, "previous": previous, "registry": str(reg_path),
            "rollback_with": f"glucotwin research rollback --to {previous}"}


def rollback(to_version: str, registry: str | None = None) -> dict[str, Any]:
    reg_path = _registry_path(registry)
    reg = json.loads(reg_path.read_text())
    if not any(m["model_version"] == to_version for m in reg["models"]):
        raise PromotionError(f"{to_version} is not in the registry")
    backup = json.loads(json.dumps(reg))
    previous = reg.get("serving", {}).get("dataset_replay")
    reg["serving"]["dataset_replay"] = to_version
    reg.setdefault("history", []).append({"at": datetime.now(UTC).isoformat(timespec="seconds"), "action": "rollback",
                                          "from": previous, "to": to_version})
    _atomic_write(reg_path, reg)
    try:
        _resolves(reg_path, to_version)
    except Exception:
        _atomic_write(reg_path, backup)
        raise
    return {"status": "rolled_back", "serving": to_version, "previous": previous}
