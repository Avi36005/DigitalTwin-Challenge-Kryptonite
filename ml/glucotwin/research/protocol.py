"""Frozen research protocol, deterministic participant folds and the split-membership file.

``freeze`` writes ``artifacts/research/<id>/splits.json`` before any fit. Every later stage re-hashes the protocol
file and refuses to run if it changed after freezing, so an outcome can never feed back into the declared design.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from glucotwin.config import fingerprint, load_experiment_config, paths

DEFAULT_EXPERIMENT = "gt-nested-2026-10-12-v1"
FINAL = "final"


class ProtocolError(RuntimeError):
    pass


def research_dir(experiment_id: str = DEFAULT_EXPERIMENT) -> Path:
    return paths().artifacts / "research" / experiment_id


def split_file_path(experiment_id: str = DEFAULT_EXPERIMENT) -> Path:
    return research_dir(experiment_id) / "splits.json"


def load_protocol(experiment_id: str = DEFAULT_EXPERIMENT) -> dict[str, Any]:
    p = load_experiment_config(experiment_id)
    if p.get("kind") != "nested-participant-benchmark":
        raise ProtocolError(f"{experiment_id} is not a nested research protocol")
    return p


def protocol_hash(experiment_id: str = DEFAULT_EXPERIMENT) -> str:
    return fingerprint(load_protocol(experiment_id))


@dataclass(frozen=True)
class FoldPlan:
    fold: str                       # "outer-1" ... "outer-5" or "final"
    assessment: tuple[str, ...]     # outer-assessment participants (empty for the final candidate)
    calibration: tuple[str, ...]
    development: tuple[str, ...]
    inner: tuple[tuple[str, ...], ...]

    def as_dict(self) -> dict[str, Any]:
        return {"fold": self.fold, "assessment": list(self.assessment), "calibration": list(self.calibration),
                "development": list(self.development), "inner": [list(f) for f in self.inner]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FoldPlan:
        return cls(d["fold"], tuple(d["assessment"]), tuple(d["calibration"]), tuple(d["development"]),
                   tuple(tuple(f) for f in d["inner"]))


def _deal(ids: list[str], k: int) -> list[list[str]]:
    out: list[list[str]] = [[] for _ in range(k)]
    for i, pid in enumerate(ids):
        out[i % k].append(pid)
    return [sorted(f) for f in out]


def make_plans(participants: list[str], cfg: dict[str, Any], seed: int,
               keys: dict[str, str] | None = None) -> list[FoldPlan]:
    """Outer folds + the final-candidate plan. Deterministic given (participants, cfg, seed).

    With ``keys`` (participant -> public source key, used when the protocol declares
    ``assignment_key: source_participant_key``) the assignment is computed on the public keys, so another installation
    with a different pseudonym salt gets the same people in the same folds."""
    if keys is not None:
        inv = {keys[p]: p for p in participants}
        if len(inv) != len(set(participants)):
            raise ProtocolError("source keys are not unique")
        plans = make_plans(sorted(inv), cfg, seed)
        m = lambda xs: tuple(sorted(inv[x] for x in xs))  # noqa: E731
        return [FoldPlan(p.fold, m(p.assessment), m(p.calibration), m(p.development), tuple(m(f) for f in p.inner))
                for p in plans]
    ids = sorted(set(participants))
    k_out = int(cfg["outer_folds"])
    if len(ids) < k_out:
        raise ProtocolError(f"{len(ids)} participants cannot fill {k_out} outer folds")
    rng = np.random.default_rng([seed, 1])
    outer = _deal(rng.permutation(ids).tolist(), k_out)
    plans = []

    def inner_plan(name: str, assessment: list[str], pool: list[str], salt: int) -> FoldPlan:
        r = np.random.default_rng([seed, 2, salt])
        perm = r.permutation(sorted(pool)).tolist()
        n_cal = max(int(cfg["calibration_min_participants"]), int(math.floor(cfg["calibration_fraction"] * len(pool))))
        cal, dev = sorted(perm[:n_cal]), perm[n_cal:]
        k_in = int(cfg["inner_folds"])
        if len(dev) < k_in:
            raise ProtocolError(f"{name}: {len(dev)} development participants cannot fill {k_in} inner folds")
        return FoldPlan(name, tuple(sorted(assessment)), tuple(cal), tuple(sorted(dev)), tuple(tuple(f) for f in _deal(dev, k_in)))

    for i, fold in enumerate(outer, start=1):
        pool = [p for p in ids if p not in fold]
        plans.append(inner_plan(f"outer-{i}", fold, pool, i))
    plans.append(inner_plan(FINAL, [], ids, 0))
    _check_disjoint(plans)
    return plans


def _check_disjoint(plans: list[FoldPlan]) -> None:
    for p in plans:
        groups = [set(p.assessment), set(p.calibration), set(p.development)]
        if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
            raise ProtocolError(f"{p.fold}: assessment/calibration/development overlap")
        inner = [set(f) for f in p.inner]
        if set().union(*inner) != groups[2] or sum(len(f) for f in inner) != len(groups[2]):
            raise ProtocolError(f"{p.fold}: inner folds do not partition the development participants")
    outer = [set(p.assessment) for p in plans if p.fold != FINAL]
    if any(outer[i] & outer[j] for i in range(len(outer)) for j in range(i + 1, len(outer))):
        raise ProtocolError("outer assessment folds overlap")


def check_required_sources(proto: dict[str, Any], statuses: dict[str, str]) -> None:
    """A protocol may declare ``requires_sources``; it cannot be frozen until each is eligible on this machine."""
    missing = [s for s in proto.get("requires_sources", []) if statuses.get(s) != "eligible_for_experiment"]
    if missing:
        raise ProtocolError(f"{proto['experiment_id']} requires {missing} to be imported and eligible first "
                            f"(current: {', '.join(f'{m}={statuses.get(m)}' for m in missing)}); nothing was frozen.")


def freeze(experiment_id: str, development_ids: list[str], external_ids: list[str], data_fingerprints: dict[str, str],
           extra: dict[str, Any] | None = None, overwrite: bool = False,
           keys: dict[str, str] | None = None) -> dict[str, Any]:
    """Write the split membership once. Re-freezing with a different protocol or membership is refused."""
    proto = load_protocol(experiment_id)
    path = split_file_path(experiment_id)
    use_keys = proto["folds"].get("assignment_key") == "source_participant_key"
    if use_keys and keys is None:
        raise ProtocolError("protocol assigns folds by public source keys, but none were provided")
    plans = make_plans(development_ids, proto["folds"], int(proto["random_seed"]), keys if use_keys else None)
    doc = {
        "experiment_id": experiment_id, "protocol_hash": fingerprint(proto),
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "development_dataset": proto["data"]["development"]["dataset"],
        "external_dataset": proto["data"]["external"]["dataset"],
        "development_participants": sorted(development_ids), "external_participants": sorted(external_ids),
        "plans": [p.as_dict() for p in plans], "data_fingerprints": data_fingerprints, **(extra or {}),
    }
    doc["split_hash"] = fingerprint({"plans": doc["plans"], "external": doc["external_participants"]})
    doc["counts_by_dataset"] = {
        proto["data"]["development"]["dataset"]: {
            "participants": len(development_ids),
            "outer_folds": len([p for p in plans if p.fold != FINAL]),
            "assessed_participants": len({x for p in plans if p.fold != FINAL for x in p.assessment}),
            "outer_assessment_group_sizes": "/".join(str(len(p.assessment)) for p in plans if p.fold != FINAL),
            "outer_calibration_group_sizes": "/".join(str(len(p.calibration)) for p in plans if p.fold != FINAL),
            "outer_development_sizes": "/".join(str(len(p.development)) for p in plans if p.fold != FINAL),
            "final_candidate_development_participants": len(plans[-1].development),
            "final_candidate_calibration_participants": len(plans[-1].calibration),
            "training_rows_note": "each outer fold trains on its development participants' chronological heads; "
                                  "early stopping uses their purged tails",
        },
        proto["data"]["external"]["dataset"]: {
            "participants": len(external_ids), "assessed_participants": len(external_ids),
            "role": "reserved external assessment (never trained, tuned or calibrated on)",
        },
    }
    if path.exists() and not overwrite:
        old = json.loads(path.read_text())
        if old["protocol_hash"] != doc["protocol_hash"] or old["split_hash"] != doc["split_hash"]:
            raise ProtocolError("Protocol or split membership changed after freezing; declare a new experiment ID.")
        return old
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2))
    return doc


TIMING_KEYS = ("fit_seconds", "seconds", "inner_fit_seconds")


def _drop_timing(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_timing(v) for k, v in obj.items() if k not in TIMING_KEYS}
    if isinstance(obj, list):
        return [_drop_timing(v) for v in obj]
    return obj


def pipeline_freeze_hash(pl: dict[str, Any]) -> str:
    """Hash of everything a frozen fold pipeline decides. Version 2 (pipelines written from 2026-10-12 on) leaves out
    wall-clock fit times so an identical re-run on another machine gives the same hash; version-1 pipelines (the
    original gt-nested-2026-10-12-v1 run) keep the hash they were frozen with."""
    payload = ({k: pl[k] for k in ("selection", "adaptation", "bundles", "modes")} |
               {"calibration": {k: v["horizons"] for k, v in pl["calibration"].items()},
                "warnings": {k: (v["primary"], v["f1_comparator"]) for k, v in pl["warnings"].items()}})
    return fingerprint(_drop_timing(payload) if pl.get("freeze_hash_version") == 2 else payload)


def load_frozen(experiment_id: str = DEFAULT_EXPERIMENT) -> dict[str, Any]:
    path = split_file_path(experiment_id)
    if not path.exists():
        raise ProtocolError(f"{experiment_id} is not frozen; run `glucotwin research freeze` first.")
    doc = json.loads(path.read_text())
    if doc["protocol_hash"] != protocol_hash(experiment_id):
        raise ProtocolError("configs/experiments protocol changed after freezing; results would not match the "
                            "declared design. Declare a new experiment ID instead of editing a frozen protocol.")
    return doc


def plans_of(doc: dict[str, Any]) -> list[FoldPlan]:
    return [FoldPlan.from_dict(p) for p in doc["plans"]]
