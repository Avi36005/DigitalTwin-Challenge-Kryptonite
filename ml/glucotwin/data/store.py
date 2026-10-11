"""Canonical normalized store: partitioned Parquet time series plus SQLite metadata.

Layout of one store directory::

    <store>/catalog.sqlite                  patients, profile attributes, import log
    <store>/patients/<patient_id>/glucose.parquet
    <store>/patients/<patient_id>/activity.parquet
    <store>/patients/<patient_id>/meals.parquet

Each patient lives in its own partition, so importing a second participant never overwrites the first.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

STORE_SCHEMA_VERSION = "1.0"
EPOCH = pd.Timestamp("2000-01-01T00:00:00Z")

GLUCOSE_COLUMNS = {
    "event_id": "string",
    "observed_at": "datetime64[ns, UTC]",
    "available_at": "datetime64[ns, UTC]",
    "value_mg_dl": "float64",
    "quality": "string",
    "flags": "string",
    "source": "string",
}
ACTIVITY_COLUMNS = {
    "event_id": "string",
    "observed_at": "datetime64[ns, UTC]",   # end of the trailing summary window
    "available_at": "datetime64[ns, UTC]",
    "window_minutes": "int64",
    "minutes_covered": "int64",
    "heart_rate_bpm": "float64",
    "mets": "float64",
    "activity_kcal": "float64",
    "quality": "string",
    "flags": "string",
    "source": "string",
}
MEAL_COLUMNS = {
    "event_id": "string",
    "observed_at": "datetime64[ns, UTC]",
    "available_at": "datetime64[ns, UTC]",
    "meal_type": "string",
    "energy_kcal": "float64",
    "carbs_g": "float64",
    "protein_g": "float64",
    "fat_g": "float64",
    "fiber_g": "float64",
    "amount_consumed_pct": "float64",
    "quality": "string",
    "flags": "string",
    "source": "string",
}
TABLES = {"glucose": GLUCOSE_COLUMNS, "activity": ACTIVITY_COLUMNS, "meals": MEAL_COLUMNS}


def to_minutes(ts: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Convert UTC timestamps to float minutes since EPOCH (internal fast representation)."""
    values = pd.to_datetime(ts, utc=True)
    return ((values - EPOCH) / pd.Timedelta(minutes=1)).to_numpy(dtype=float)


def from_minutes(m: float) -> datetime:
    micros = int(round(float(m) * 60_000_000))
    return (EPOCH + pd.Timedelta(microseconds=micros)).to_pydatetime()


def empty_table(kind: str) -> pd.DataFrame:
    cols = TABLES[kind]
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in cols.items()})


def conform(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    cols = TABLES[kind]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{kind} table missing columns {missing}")
    out = df[list(cols)].copy()
    for c, t in cols.items():
        if t.startswith("datetime64"):
            out[c] = pd.to_datetime(out[c], utc=True)
        else:
            out[c] = out[c].astype(t)
    for c, t in cols.items():
        if t == "float64":
            vals = out[c].to_numpy(dtype=float)
            if np.isinf(vals).any():
                raise ValueError(f"{kind}.{c} contains non-finite values")
    out = out.sort_values(["available_at", "observed_at", "event_id"], kind="mergesort").reset_index(drop=True)
    if out["event_id"].duplicated().any():
        raise ValueError(f"{kind} table has duplicate event_id values")
    return out


@dataclass
class PatientData:
    meta: dict[str, Any]
    profile: list[dict[str, Any]]
    glucose: pd.DataFrame
    activity: pd.DataFrame
    meals: pd.DataFrame
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def patient_id(self) -> str:
        return self.meta["patient_id"]


class Store:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    @property
    def catalog_path(self) -> Path:
        return self.directory / "catalog.sqlite"

    def exists(self) -> bool:
        return self.catalog_path.exists()

    def _connect(self) -> sqlite3.Connection:
        self.directory.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.catalog_path)
        con.execute(
            "CREATE TABLE IF NOT EXISTS store_info (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS patients (patient_id TEXT PRIMARY KEY, mode TEXT NOT NULL, "
            "sort_key TEXT NOT NULL, meta_json TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS profile (patient_id TEXT NOT NULL, name TEXT NOT NULL, "
            "attr_json TEXT NOT NULL, PRIMARY KEY (patient_id, name))"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS import_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
            "detail_json TEXT NOT NULL)"
        )
        row = con.execute("SELECT value FROM store_info WHERE key='schema_version'").fetchone()
        if row is None:
            con.execute("INSERT INTO store_info VALUES ('schema_version', ?)", (STORE_SCHEMA_VERSION,))
            con.commit()
        elif row[0] != STORE_SCHEMA_VERSION:
            con.close()
            raise RuntimeError(
                f"Store {self.directory} has schema {row[0]}, expected {STORE_SCHEMA_VERSION}; re-run the import."
            )
        return con

    def set_info(self, key: str, value: Any) -> None:
        with self._connect() as con:
            con.execute("INSERT OR REPLACE INTO store_info VALUES (?, ?)", (key, json.dumps(value)))

    def get_info(self, key: str, default: Any = None) -> Any:
        if not self.exists():
            return default
        with self._connect() as con:
            row = con.execute("SELECT value FROM store_info WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def write_patient(self, pdata: PatientData) -> None:
        pid = pdata.patient_id
        pdir = self.directory / "patients" / pid
        pdir.mkdir(parents=True, exist_ok=True)
        for kind in TABLES:
            df = conform(getattr(pdata, kind), kind)
            df.to_parquet(pdir / f"{kind}.parquet", index=False)
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO patients VALUES (?, ?, ?, ?)",
                (pid, pdata.meta["mode"], pdata.meta.get("sort_key", pid), json.dumps(pdata.meta, default=str)),
            )
            con.execute("DELETE FROM profile WHERE patient_id=?", (pid,))
            con.executemany(
                "INSERT INTO profile VALUES (?, ?, ?)",
                [(pid, a["name"], json.dumps(a, default=str)) for a in pdata.profile],
            )

    def log_import(self, detail: dict[str, Any]) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO import_log (at, detail_json) VALUES (?, ?)",
                (datetime.now(UTC).isoformat(timespec="seconds"), json.dumps(detail, default=str)),
            )

    def patient_ids(self) -> list[str]:
        if not self.exists():
            return []
        with self._connect() as con:
            rows = con.execute("SELECT patient_id FROM patients ORDER BY sort_key").fetchall()
        return [r[0] for r in rows]

    def meta(self, patient_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("SELECT meta_json FROM patients WHERE patient_id=?", (patient_id,)).fetchone()
        if row is None:
            raise KeyError(patient_id)
        return json.loads(row[0])

    def profile(self, patient_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT attr_json FROM profile WHERE patient_id=? ORDER BY rowid", (patient_id,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def load(self, patient_id: str) -> PatientData:
        meta = self.meta(patient_id)
        pdir = self.directory / "patients" / patient_id
        tables = {}
        for kind in TABLES:
            path = pdir / f"{kind}.parquet"
            tables[kind] = conform(pd.read_parquet(path), kind) if path.exists() else empty_table(kind)
        return PatientData(meta, self.profile(patient_id), tables["glucose"], tables["activity"], tables["meals"])
