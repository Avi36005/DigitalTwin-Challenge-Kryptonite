"""Replay sessions: the backend owns the replay clock.

* Each session has its own clock, revision, twin engine and lock; sessions never share state.
* ``play`` advances the clock lazily on each read in whole 5-minute steps
  (``speed`` replay-minutes per wall-clock second), so release is deterministic given the clock.
* ``seek`` and ``reset`` start a new revision: the engine is rebuilt from scratch using only events
  released by the new clock. Old-revision cursors are rejected; old forecasts stay only in the audit DB.
* In the public synthetic demonstration (``public.PublicConfig.enabled``) every session belongs to one visitor: another
  visitor's, an evicted or an expired session is reported exactly like an unknown one. Sessions are capped per visitor
  and in total (least recently used evicted) and expire after a period without use.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from glucotwin.data.store import from_minutes, to_minutes
from glucotwin.dataset import load_settings
from glucotwin.events import EventDefinition
from glucotwin.serving import ServingModel
from glucotwin.twin import TwinEngine

from .catalog import Catalog, SourceTimeline
from .public import PublicConfig
from .storage import LocalStore

STEP_MINUTES = 5
STALE_MINUTES = 15.0


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Session:
    id: str
    patient_id: str
    mode: str
    timeline: SourceTimeline
    clock: float
    speed: float
    status: str = "ready"
    revision: int = 1
    engine: TwinEngine | None = None
    play_anchor_wall: float | None = None
    play_anchor_clock: float | None = None
    error: dict[str, str] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    lock: threading.RLock = field(default_factory=threading.RLock)
    owner: str | None = None        # public demo only: hash of the visitor cookie
    last_used: float = 0.0          # SessionManager.now() at the last access (public demo expiry and eviction)


class SessionManager:
    def __init__(self, catalog: Catalog, serving: dict[str, ServingModel | None], store: LocalStore,
                 public: PublicConfig | None = None):
        self.catalog = catalog
        self.serving = serving
        self.store = store
        self.public = public or PublicConfig()
        self.now = time.monotonic   # replaceable in tests; only used for public-demo expiry and eviction
        self.sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        st = load_settings()
        self.event_def: EventDefinition = st.event

    # ------------------------------------------------------------------ lifecycle

    def create(self, patient_id: str, mode: str, start_at, speed: float, owner: str | None = None) -> Session:
        if not self.catalog.has(patient_id):
            raise ApiError(404, "patient_not_found", f"Unknown participant {patient_id!r}.")
        if self.catalog.mode(patient_id) != mode:
            raise ApiError(422, "mode_mismatch",
                           f"Participant {patient_id!r} is available in mode {self.catalog.mode(patient_id)!r}.")
        tl = self.catalog.timeline(patient_id)
        clock = tl.start
        if start_at is not None:
            clock = self._validate_time(tl, start_at)
        sid = uuid.uuid4().hex[:12]
        s = Session(sid, patient_id, mode, tl, clock, speed, owner=owner, last_used=self.now())
        with s.lock:
            self._rebuild(s)
        with self._lock:
            if self.public.enabled:
                self._sweep_locked()
                mine = [x for x in self.sessions.values() if x.owner == owner]
                over = len(mine) - self.public.max_sessions_per_visitor + 1
                for old in sorted(mine, key=lambda x: x.last_used)[:max(0, over)]:
                    self._drop_locked(old.id, "evicted_visitor_limit")
                extra = len(self.sessions) - self.public.max_sessions + 1
                for old in sorted(self.sessions.values(), key=lambda x: x.last_used)[:max(0, extra)]:
                    self._drop_locked(old.id, "evicted_global_limit")
            self.sessions[sid] = s
        self.store.log(sid, "create", {"patient_id": patient_id, "mode": mode, "clock": clock})
        return s

    def get(self, sid: str, owner: str | None = None) -> Session:
        s = self.sessions.get(sid)
        if s is not None and self.public.enabled:
            if s.owner != owner:
                s = None  # another visitor's session is indistinguishable from an unknown one
            elif self._expired(s):
                with self._lock:
                    self._drop_locked(sid, "expired")
                s = None
            else:
                s.last_used = self.now()
        if s is None:
            raise ApiError(404, "session_not_found", f"Unknown replay session {sid!r}.")
        return s

    def visible(self, owner: str | None = None) -> list[Session]:
        """Sessions the caller may see: all of them locally; only the visitor's own, unexpired ones in public mode."""
        if not self.public.enabled:
            return list(self.sessions.values())
        with self._lock:
            self._sweep_locked()
            return [s for s in self.sessions.values() if s.owner == owner]

    def latest_for(self, patient_id: str, owner: str | None = None) -> Session | None:
        cands = [s for s in self.visible(owner) if s.patient_id == patient_id]
        return cands[-1] if cands else None

    def _expired(self, s: Session) -> bool:
        return self.now() - s.last_used > self.public.session_idle_minutes * 60.0

    def _sweep_locked(self) -> None:
        for sid in [x.id for x in self.sessions.values() if self._expired(x)]:
            self._drop_locked(sid, "expired")

    def _drop_locked(self, sid: str, reason: str) -> None:
        s = self.sessions.pop(sid, None)
        if s is not None:  # the twin state is freed once no in-flight request holds it; issued forecasts stay in the audit DB
            self.store.log(sid, "removed", {"reason": reason})

    def _validate_time(self, tl: SourceTimeline, ts) -> float:
        m = float(to_minutes([ts])[0])
        if not (tl.start - 1e-6 <= m <= tl.end + 1e-6):
            raise ApiError(422, "time_out_of_bounds",
                           f"Requested time is outside the replay timeline ({from_minutes(tl.start).isoformat()} "
                           f"to {from_minutes(tl.end).isoformat()}).")
        return m

    def _engine(self, s: Session) -> TwinEngine:
        serving = self.serving.get(s.mode)
        b = self.catalog.boundaries.get(s.patient_id) if s.mode == "dataset_replay" else None
        collect_from = b.train_end if b is not None else -np.inf
        return TwinEngine(s.id, s.revision, self.catalog.meta(s.patient_id), serving, self.event_def, b, collect_from)

    def _rebuild(self, s: Session) -> None:
        s.engine = self._engine(s)
        self._advance(s, s.clock)

    def _advance(self, s: Session, clock: float) -> None:
        clock = min(clock, s.timeline.end)
        released = s.timeline.released(clock)
        issued = s.engine.advance(released, clock)
        s.clock = clock
        if issued:
            self.store.save_forecasts([{k: v for k, v in f.items() if not k.startswith("_")} for f in issued])
        if s.clock >= s.timeline.end - 1e-6:
            s.status = "completed"
            s.play_anchor_wall = None

    def sync(self, s: Session) -> None:
        """Advance a playing session to the clock implied by wall time (called on every read)."""
        if s.status != "playing" or s.play_anchor_wall is None:
            return
        elapsed = time.monotonic() - s.play_anchor_wall
        steps = int(elapsed * s.speed // STEP_MINUTES)
        target = s.play_anchor_clock + steps * STEP_MINUTES
        if target > s.clock + 1e-6:
            self._advance(s, target)

    def control(self, sid: str, action: str, steps: int | None, seek_to, speed: float | None,
                owner: str | None = None) -> Session:
        s = self.get(sid, owner)
        with s.lock:
            self.sync(s)
            if speed is not None:
                s.speed = speed
                if s.status == "playing":
                    s.play_anchor_wall, s.play_anchor_clock = time.monotonic(), s.clock
            if action == "play":
                if s.status == "completed":
                    raise ApiError(409, "replay_completed", "Replay reached the end of the recording; reset or seek.")
                if s.status != "playing":
                    s.status = "playing"
                    s.play_anchor_wall, s.play_anchor_clock = time.monotonic(), s.clock
            elif action == "pause":
                if s.status == "playing":
                    s.status = "paused"
                    s.play_anchor_wall = None
            elif action == "step":
                if s.status == "completed":
                    raise ApiError(409, "replay_completed", "Replay reached the end of the recording; reset or seek.")
                s.status = "paused"
                s.play_anchor_wall = None
                self._advance(s, s.clock + (steps or 1) * STEP_MINUTES)
            elif action in ("seek", "reset"):
                target = s.timeline.start if action == "reset" else self._validate_time(s.timeline, seek_to)
                s.revision += 1
                s.clock = target
                s.status = "ready" if action == "reset" else "paused"
                s.play_anchor_wall = None
                self._rebuild(s)
            self.store.log(sid, action, {"clock": s.clock, "revision": s.revision, "steps": steps})
            return s

    # ------------------------------------------------------------------ views

    def event_payload(self, s: Session, entry) -> dict[str, Any]:
        _, _, _, eid, table, row = entry
        df = getattr(s.timeline.pdata, table)
        r = df.iloc[row]
        flags = [f for f in str(r["flags"]).split(";") if f]
        if table == "glucose":
            kind, units, values = "glucose", {"value": "mg/dL"}, {"value": _f(r["value_mg_dl"])}
        elif table == "activity":
            kind = "activity"
            units = {"heart_rate": "bpm", "mets": "MET", "activity_energy": "kcal", "window": "min",
                     "minutes_covered": "min"}
            values = {"heart_rate": _f(r["heart_rate_bpm"]), "mets": _f(r["mets"]),
                      "activity_energy": _f(r["activity_kcal"]), "window": _f(r["window_minutes"]),
                      "minutes_covered": _f(r["minutes_covered"])}
        else:
            kind = "meal"
            units = {"energy": "kcal", "carbohydrate": "g", "protein": "g", "fat": "g", "fiber": "g",
                     "amount_consumed": "%"}
            values = {"meal_type": str(r["meal_type"]), "energy": _f(r["energy_kcal"]), "carbohydrate": _f(r["carbs_g"]),
                      "protein": _f(r["protein_g"]), "fat": _f(r["fat_g"]), "fiber": _f(r["fiber_g"]),
                      "amount_consumed": _f(r["amount_consumed_pct"])}
        return {"schema_version": "1.0", "event_id": eid, "patient_id": s.patient_id, "kind": kind,
                "observed_at": r["observed_at"].to_pydatetime(warn=False), "available_at": r["available_at"].to_pydatetime(warn=False),
                "source": str(r["source"]), "quality": str(r["quality"]), "quality_flags": flags, "units": units,
                "values": values}

    def freshness(self, s: Session) -> dict[str, Any]:
        released = s.timeline.released(s.clock).glucose
        if not len(released):
            return {"latest_glucose_at": None, "latest_glucose_age_minutes": None,
                    "stale_threshold_minutes": STALE_MINUTES, "status": "no_data"}
        last = released["observed_at"].max()
        age = s.clock - float(to_minutes([last])[0])
        return {"latest_glucose_at": last.to_pydatetime(warn=False), "latest_glucose_age_minutes": round(age, 1),
                "stale_threshold_minutes": STALE_MINUTES, "status": "stale" if age > STALE_MINUTES else "fresh"}


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None
