"""Opt-in acquisition and verification of the CGMacros source files.

* ``download`` fetches the published files (PhysioNet or its byte-identical open-data mirror) into
  ``data/raw/cgmacros/1.0.0``. It resumes partial downloads and verifies every file against the
  published ``SHA256SUMS.txt``.
* ``verify`` works on an existing local copy (e.g. one fetched manually with ``wget``) and fails
  clearly if a required file is missing, partial or changed.
* ``extract_tables`` extracts only the CSV tables from the archive (meal photographs are not needed),
  rejecting unsafe archive paths. Dataset contents are never executed or unpickled.

Running any of these again is idempotent.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from glucotwin.config import file_sha256, load_config, paths


class SourceVerificationError(RuntimeError):
    pass


@dataclass
class SourceFile:
    relative_path: str
    size_bytes: int
    sha256: str
    expected_sha256: str | None

    @property
    def verified(self) -> bool:
        return self.expected_sha256 is not None and self.sha256 == self.expected_sha256


def raw_dir() -> Path:
    cfg = load_config("data")["dataset"]
    return paths().raw / cfg["raw_subdir"]


def read_checksums(directory: Path) -> dict[str, str]:
    sums = directory / "SHA256SUMS.txt"
    if not sums.exists():
        raise SourceVerificationError(f"Missing {sums}; run `glucotwin data download` or copy it from PhysioNet.")
    out: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            out[parts[1]] = parts[0].lower()
    return out


def _fetch(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    start = tmp.stat().st_size if tmp.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "glucotwin-research-download/0.1"})
    if start:
        req.add_header("Range", f"bytes={start}-")
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https URLs from config
        mode = "ab" if start and resp.status == 206 else "wb"
        with open(tmp, mode) as fh:
            shutil.copyfileobj(resp, fh, length=1 << 20)
    tmp.replace(dest)


def download(use_mirror: bool = True, force: bool = False) -> list[SourceFile]:
    cfg = load_config("data")["dataset"]
    directory = raw_dir()
    directory.mkdir(parents=True, exist_ok=True)
    base = cfg["mirror_base_url"] if use_mirror else cfg["files_base_url"]
    names = list(cfg["metadata_files"]) + [cfg["archive"]]
    # Fetch the checksum file first, from the primary distribution when possible.
    for name in ["SHA256SUMS.txt", *[n for n in names if n != "SHA256SUMS.txt"]]:
        dest = directory / name
        if dest.exists() and not force:
            continue
        print(f"Downloading {name} ...", flush=True)
        _fetch(base + name, dest)
    return verify()


def verify(required: list[str] | None = None) -> list[SourceFile]:
    cfg = load_config("data")["dataset"]
    directory = raw_dir()
    expected = read_checksums(directory)
    required = required or [cfg["archive"], "DataDictionary_Bio.csv", "DataDictionary_CGMacros-00X.csv"]
    results: list[SourceFile] = []
    for name in sorted(set(required) | {p.name for p in directory.iterdir() if p.name in expected}):
        path = directory / name
        if not path.exists():
            raise SourceVerificationError(
                f"Required source file missing: {path}. Run `glucotwin data download` "
                f"or place the PhysioNet file there."
            )
        digest = file_sha256(path)
        sf = SourceFile(name, path.stat().st_size, digest, expected.get(name))
        if not sf.verified:
            raise SourceVerificationError(
                f"Checksum mismatch for {name}: got {digest}, expected {expected.get(name)}. "
                "The file is partial or differs from CGMacros 1.0.0; delete it and download again."
            )
        results.append(sf)
    return results


def _safe_member(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and not name.startswith(("/", "\\"))


def extract_tables(dest: Path) -> list[str]:
    """Extract CSV tables only (idempotent). Returns the extracted relative paths."""
    cfg = load_config("data")["dataset"]
    archive = raw_dir() / cfg["archive"]
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir() or not name.lower().endswith(".csv"):
                continue
            if "__MACOSX" in name or PurePosixPath(name).name.startswith("._"):
                continue
            if not _safe_member(name):
                raise SourceVerificationError(f"Unsafe archive path rejected: {name!r}")
            target = dest / PurePosixPath(name).name
            if not target.exists() or target.stat().st_size != info.file_size:
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
            extracted.append(target.name)
    return sorted(extracted)


def write_provenance(files: list[SourceFile], extracted: list[str], parser_version: str, out: Path) -> dict:
    cfg = load_config("data")["dataset"]
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(out.read_text()) if out.exists() else {}
    manifest = {
        "dataset": cfg["name"],
        "version": cfg["version"],
        "landing_page": cfg["landing_page"],
        "doi": cfg["doi"],
        "license": cfg["license"],
        "license_url": cfg["license_url"],
        "citation": cfg["citation"],
        "retrieved_at": previous.get("retrieved_at") or datetime.now(UTC).isoformat(timespec="seconds"),
        "parser_version": parser_version,
        "files": [
            {"relative_path": f.relative_path, "size_bytes": f.size_bytes, "sha256": f.sha256, "verified": f.verified}
            for f in files
        ],
        "extracted_tables": extracted,
    }
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
