"""Local SQLite persistence: issued forecasts (immutable audit), session log and review acknowledgements."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class LocalStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(
            """
            CREATE TABLE IF NOT EXISTS forecasts (
                forecast_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, revision INTEGER NOT NULL,
                as_of TEXT NOT NULL, model_version TEXT, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_forecasts_session ON forecasts(session_id, revision, as_of);
            CREATE TABLE IF NOT EXISTS acknowledgements (
                alert_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, acknowledged_at TEXT NOT NULL, note TEXT);
            CREATE TABLE IF NOT EXISTS session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, at TEXT NOT NULL,
                action TEXT NOT NULL, detail TEXT);
            """
        )
        self._con.commit()

    def save_forecasts(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._lock:
            # INSERT OR IGNORE: an issued forecast is immutable; re-issuing the same ID never rewrites it
            self._con.executemany(
                "INSERT OR IGNORE INTO forecasts VALUES (?, ?, ?, ?, ?, ?)",
                [(r["forecast_id"], r["session_id"], r["session_revision"], str(r["as_of"]), r.get("model_version"),
                  json.dumps(r, default=str)) for r in rows],
            )
            self._con.commit()

    def stored_forecast(self, forecast_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._con.execute("SELECT payload FROM forecasts WHERE forecast_id=?", (forecast_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def acknowledge(self, alert_id: str, session_id: str, note: str | None) -> dict[str, Any]:
        with self._lock:
            row = self._con.execute(
                "SELECT acknowledged_at, note FROM acknowledgements WHERE alert_id=?", (alert_id,)).fetchone()
            if row is None:
                at = datetime.now(UTC).isoformat(timespec="seconds")
                self._con.execute("INSERT INTO acknowledgements VALUES (?, ?, ?, ?)", (alert_id, session_id, at, note))
                self._con.commit()
                return {"acknowledged_at": at, "note": note}
        return {"acknowledged_at": row[0], "note": row[1]}

    def acknowledgement(self, alert_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._con.execute(
                "SELECT acknowledged_at, note FROM acknowledgements WHERE alert_id=?", (alert_id,)).fetchone()
        return {"acknowledged_at": row[0], "note": row[1]} if row else None

    def log(self, session_id: str, action: str, detail: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._con.execute("INSERT INTO session_log (session_id, at, action, detail) VALUES (?, ?, ?, ?)",
                              (session_id, datetime.now(UTC).isoformat(timespec="seconds"), action,
                               json.dumps(detail or {}, default=str)))
            self._con.commit()
