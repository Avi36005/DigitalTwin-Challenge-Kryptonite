"""Configuration loading and repository paths.

All paths are resolved relative to the repository root (or ``GLUCOTWIN_HOME``) so that no
developer-specific absolute path is required.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    env = os.environ.get("GLUCOTWIN_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "configs").exists():
            return parent
    raise RuntimeError("Cannot locate repository root; set GLUCOTWIN_HOME.")


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def configs(self) -> Path:
        return self.root / "configs"

    @property
    def raw(self) -> Path:
        return Path(os.environ.get("GLUCOTWIN_RAW_DIR", self.root / "data" / "raw"))

    @property
    def processed(self) -> Path:
        return Path(os.environ.get("GLUCOTWIN_PROCESSED_DIR", self.root / "data" / "processed"))

    @property
    def private(self) -> Path:
        return self.root / "data" / "private"

    @property
    def synthetic(self) -> Path:
        return self.root / "data" / "synthetic" / "generated"

    @property
    def artifacts(self) -> Path:
        return Path(os.environ.get("GLUCOTWIN_ARTIFACTS_DIR", self.root / "artifacts"))

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def var(self) -> Path:
        return Path(os.environ.get("GLUCOTWIN_VAR_DIR", self.root / "var"))


def paths() -> Paths:
    return Paths(repo_root())


@lru_cache(maxsize=16)
def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration {path} must be a mapping")
    return data


def load_config(name: str) -> dict[str, Any]:
    """Load ``configs/<name>.yaml``."""
    path = paths().configs / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Missing configuration file: {path}")
    return _load_yaml(str(path))


def fingerprint(obj: Any) -> str:
    """Stable short SHA-256 of a JSON-serializable object."""
    blob = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()
