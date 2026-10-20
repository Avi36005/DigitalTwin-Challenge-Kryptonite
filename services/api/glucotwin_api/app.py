"""GlucoTwin research API (``/api/v1``, schema_version 1.0).

Local research demonstration only: binds to loopback by default, narrow CORS, no authentication,
no external notifications. Not a medical device and not production software.

Opt-in public synthetic demonstration (``GLUCOTWIN_PUBLIC_DEMO=1``, ``glucotwin serve --public-demo``): synthetic
participants only (recorded-data routes answer 403), an anonymous visitor cookie keeps each visitor's replay sessions
private, sessions are capped and expire, and requests are rate-limited (``public.py``). With ``GLUCOTWIN_WEB_DIST`` set
to a built ``apps/web/dist`` the same process also serves the web app, so one port serves everything.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from glucotwin import __version__
from glucotwin.config import paths
from glucotwin.data.store import from_minutes
from glucotwin.evaluation.report import build_report
from glucotwin.schemas import (
    AcknowledgementRequest,
    Alert,
    AlertList,
    ControlCommand,
    CreateSessionRequest,
    DatasetInventory,
    ErrorEnvelope,
    EvaluationList,
    EvaluationReport,
    EventPage,
    ForecastPage,
    Health,
    LatestForecast,
    PatientDetail,
    PatientPage,
    Readiness,
    ReplaySession,
    ReplaySessionList,
    ResearchReport,
    ResearchSummaryList,
    ServingList,
    SessionProfile,
    TwinState,
)
from glucotwin.serving import load_serving
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import evidence, snapshot
from . import public as pub
from .catalog import Catalog
from .replay import STALE_MINUTES, ApiError, Session, SessionManager
from .storage import LocalStore

ERRORS = {404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}}


SYNTHETIC_ONLY = "This public demonstration serves synthetic participants only."


class AppState:
    def __init__(self) -> None:
        self.public = pub.load_config()
        self.catalog = Catalog()
        self.serving: dict[str, Any] = {}
        self.serving_errors: dict[str, str] = {}
        for mode in ("dataset_replay", "synthetic_demo"):
            if self.public.enabled and mode == "dataset_replay":
                self.serving[mode] = None  # never loaded in the public demonstration
                self.serving_errors[mode] = "Not served in the public synthetic demonstration."
                continue
            try:
                self.serving[mode] = load_serving(mode)
                if self.serving[mode] is None:
                    self.serving_errors[mode] = "No registered and verified model artifact for this mode."
            except Exception as exc:  # report, never crash startup
                self.serving[mode] = None
                self.serving_errors[mode] = f"Model artifact failed verification: {exc}"
        self.store = LocalStore(paths().var / "glucotwin.sqlite3")
        self.sessions = SessionManager(self.catalog, self.serving, self.store, self.public)
        self.limiter = pub.RateLimiter()


def create_app() -> FastAPI:
    app = FastAPI(
        title="GlucoTwin research API",
        version=__version__,
        description="Student research proof of concept. Recorded-data replay and synthetic demonstration only; "
                    "not for clinical use.",
    )
    origins = os.environ.get("GLUCOTWIN_CORS_ORIGINS",
                             "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in origins.split(",") if o.strip()],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    state = AppState()
    app.state.gt = state
    cfg = state.public
    log = logging.getLogger("uvicorn.error")
    if cfg.enabled:
        log.info("GlucoTwin public synthetic demonstration: synthetic participants only; sessions private per visitor, "
                 "at most %d per visitor and %d in total, removed after %d idle minutes; %d requests/min per visitor, "
                 "%d per IP.", cfg.max_sessions_per_visitor, cfg.max_sessions, cfg.session_idle_minutes,
                 cfg.visitor_requests_per_minute, cfg.ip_requests_per_minute)

    if cfg.enabled:
        # Added before the request-ID middleware, so it runs inside it and its 429s carry a request ID.
        @app.middleware("http")
        async def visitor(request: Request, call_next):
            token = request.cookies.get(pub.COOKIE)
            fresh = not pub.valid_token(token)
            if fresh:
                token = pub.new_token()
            request.state.visitor = pub.owner_of(token)
            if request.url.path.startswith("/api/"):
                ip = request.client.host if request.client else "unknown"
                if cfg.trust_proxy and request.headers.get("x-forwarded-for"):
                    ip = request.headers["x-forwarded-for"].split(",")[0].strip()
                if not (state.limiter.allow("v:" + request.state.visitor, cfg.visitor_requests_per_minute)
                        and state.limiter.allow("ip:" + ip, cfg.ip_requests_per_minute)):
                    response = err(request, 429, "rate_limited",
                                   "Too many requests from this browser or network; wait a minute and try again.")
                    response.headers["Retry-After"] = "60"
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
            if fresh:
                response.set_cookie(pub.COOKIE, token, max_age=pub.COOKIE_MAX_AGE, path="/", httponly=True,
                                    samesite="lax", secure=cfg.cookie_secure)
            return response

    def owner(request: Request) -> str | None:
        return getattr(request.state, "visitor", None) if cfg.enabled else None

    def synthetic_only(patient_id: str | None = None, mode: str | None = None) -> None:
        if cfg.enabled and (mode == "dataset_replay" or (
                patient_id is not None and state.catalog.has(patient_id)
                and state.catalog.mode(patient_id) == "dataset_replay")):
            raise ApiError(403, "public_demo_synthetic_only", SYNTHETIC_ONLY)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    def err(request: Request, status: int, code: str, message: str, details=None) -> JSONResponse:
        body = {"schema_version": "1.0", "error": {"code": code, "message": message,
                                                   "request_id": getattr(request.state, "request_id", None),
                                                   "details": details}}
        return JSONResponse(status_code=status, content=body)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return err(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"loc": [str(x) for x in e.get("loc", [])], "msg": str(e.get("msg"))} for e in exc.errors()]
        return err(request, 422, "validation_error", "The request was not valid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return err(request, exc.status_code, "not_found" if exc.status_code == 404 else "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        return err(request, 500, "internal_error", "Unexpected server error. See server logs for the request ID.")

    api = APIRouter(prefix="/api/v1")

    # ------------------------------------------------------------------ health

    @api.get("/health", response_model=Health)
    def health():
        limits = ({"session_idle_minutes": cfg.session_idle_minutes,
                   "max_sessions_per_visitor": cfg.max_sessions_per_visitor} if cfg.enabled else None)
        return {"status": "ok", "service": "glucotwin-api", "version": __version__, "public_demo": cfg.enabled,
                "public_demo_limits": limits}

    @api.get("/health/ready", response_model=Readiness)
    def ready():
        cat = state.catalog
        ds = "dataset_replay" in cat.stores
        syn = "synthetic_demo" in cat.stores
        rep = build_report()
        out = {
            "dataset": {"ready": ds, "detail": "CGMacros store loaded." if ds else
                        "CGMacros not imported. Run `make data` after downloading (see README)."},
            "synthetic": {"ready": syn, "detail": "Synthetic fixtures loaded." if syn else
                          "Synthetic fixtures missing. Run `make synthetic`."},
            "model": {"ready": any(state.serving.values()),
                      "detail": "; ".join(
                          f"{m}: {s.model_version if s else state.serving_errors.get(m, 'unavailable')}"
                          for m, s in state.serving.items()),
                      "version": (state.serving.get("dataset_replay") or state.serving.get("synthetic_demo")
                                  or type("x", (), {"model_version": None})).model_version},
            "evaluation": {"ready": rep["status"] == "completed", "detail": rep["status_message"],
                           "version": rep.get("experiment_id")},
        }
        out["ready"] = bool((ds or syn) and out["model"]["ready"])
        return out

    # ------------------------------------------------------------------ patients

    def summary(pid: str, request: Request) -> dict[str, Any]:
        m = state.catalog.meta(pid)
        prof = state.catalog.profile(pid)
        s = state.sessions.latest_for(pid, owner(request))
        attrs = [{"name": a["name"], "label": a["label"], "unit": a.get("unit"),
                  "present_in_source": a["status"] != "missing_in_source", "source": a.get("source"),
                  "availability_rule": a.get("availability_rule"), "note": a.get("note")} for a in prof]
        return {
            "schema_version": "1.0", "patient_id": pid, "display_alias": m["display_alias"], "mode": m["mode"],
            "dataset": m["dataset"], "cohort": m["cohort"],
            "eligible_for_primary_analysis": bool(m.get("eligible_for_primary_analysis")),
            "exclusion_reason": m.get("exclusion_reason"), "attributes": attrs,
            "missing_fields": [a["label"] for a in prof if a["status"] == "missing_in_source"],
            "coverage": m["coverage"],
            "active_session": ({"session_id": s.id, "status": s.status, "clock_at": from_minutes(s.clock),
                                "revision": s.revision} if s else None),
        }

    @api.get("/patients", response_model=PatientPage)
    def patients(request: Request, mode: Literal["dataset_replay", "synthetic_demo"] | None = None,
                 cohort: str | None = Query(None, max_length=60), eligible: bool | None = None,
                 q: str | None = Query(None, max_length=80),
                 sort: Literal["alias", "recording_days", "coverage", "meals"] = "alias",
                 order: Literal["asc", "desc"] = "asc",
                 limit: int = Query(100, ge=1, le=200), cursor: str | None = None):
        """Server-side filtering and stable sorting; ``total`` counts every match, not just this page."""
        synthetic_only(mode=mode)
        all_ids = state.catalog.ids()
        if cfg.enabled:
            all_ids = [p for p in all_ids if state.catalog.mode(p) == "synthetic_demo"]
        ids = [p for p in all_ids if mode is None or state.catalog.mode(p) == mode]
        if cohort:
            ids = [p for p in ids if state.catalog.meta(p)["cohort"]["label"] == cohort]
        if eligible is not None:
            ids = [p for p in ids if bool(state.catalog.meta(p).get("eligible_for_primary_analysis")) == eligible]
        if q:
            needle = q.strip().lower()
            ids = [p for p in ids if needle in f"{state.catalog.meta(p)['display_alias']} {p} "
                                               f"{state.catalog.meta(p)['cohort']['label']}".lower()]
        cov = {"recording_days": "recording_days", "coverage": "glucose_coverage_fraction", "meals": "meals_logged"}

        def key(p: str):
            m = state.catalog.meta(p)
            if sort == "alias":
                return (0, m["display_alias"], p)
            v = m["coverage"].get(cov[sort])
            return (1, 0.0, p) if v is None else (0, float(v), p)  # missing values sort last in both directions

        present = sorted([p for p in ids if key(p)[0] == 0], key=key, reverse=order == "desc")
        ids = present + sorted([p for p in ids if key(p)[0] == 1])
        start = 0
        if cursor:
            try:
                start = int(base64.urlsafe_b64decode(cursor.encode()).decode())
                if start < 0:  # a negative index would count back from the end of the list
                    raise ValueError(start)
            except Exception as exc:
                raise ApiError(422, "invalid_cursor", "Cursor is not valid.") from exc
        page = ids[start:start + limit]
        nxt = base64.urlsafe_b64encode(str(start + limit).encode()).decode() if start + limit < len(ids) else None
        return {"items": [summary(p, request) for p in page], "next_cursor": nxt, "total": len(ids),
                "total_unfiltered": len(all_ids)}

    @api.get("/patients/{patient_id}", response_model=PatientDetail, responses=ERRORS)
    def patient(patient_id: str, request: Request):
        if not state.catalog.has(patient_id):
            raise ApiError(404, "patient_not_found", f"Unknown participant {patient_id!r}.")
        synthetic_only(patient_id)
        m = state.catalog.meta(patient_id)
        b = state.catalog.boundaries.get(patient_id) if m["mode"] == "dataset_replay" else None
        segs = None
        if b is not None:
            segs = [{"name": name, "start_at": from_minutes(lo), "end_at": from_minutes(min(hi, b.end))}
                    for name, (lo, hi) in b.segment_bounds().items()]
        return {**summary(patient_id, request), "time_policy": m["time_policy"],
                "availability_policy_id": m["availability_policy_id"], "notes": m.get("notes", []),
                "evaluation_segments": segs}

    # ------------------------------------------------------------------ sessions

    def session_view(s: Session) -> dict[str, Any]:
        m = state.catalog.meta(s.patient_id)
        return {
            "schema_version": "1.0", "id": s.id, "patient_id": s.patient_id,
            "patient_alias": m["display_alias"], "created_at": s.created_at, "mode": s.mode,
            "clock_at": from_minutes(s.clock), "status": s.status, "speed": s.speed, "revision": s.revision,
            "timeline": {"start_at": from_minutes(s.timeline.start), "end_at": from_minutes(s.timeline.end),
                         "step_minutes": 5},
            "time_policy": m["time_policy"], "freshness": state.sessions.freshness(s),
            "released_event_count": s.timeline.released_count(s.clock), "error": s.error,
        }

    def synced(sid: str, request: Request) -> Session:
        s = state.sessions.get(sid, owner(request))
        with s.lock:
            state.sessions.sync(s)
        return s

    @api.get("/replay/sessions", response_model=ReplaySessionList)
    def list_sessions(request: Request, limit: int = Query(50, ge=1, le=200)):
        items = sorted(state.sessions.visible(owner(request)), key=lambda x: x.created_at, reverse=True)[:limit]
        out = []
        for s in items:
            with s.lock:
                state.sessions.sync(s)
                out.append(session_view(s))
        return {"schema_version": "1.0", "items": out}

    @api.post("/replay/sessions", response_model=ReplaySession, status_code=201, responses=ERRORS)
    def create_session(req: CreateSessionRequest, request: Request):
        synthetic_only(req.patient_id, req.mode)
        s = state.sessions.create(req.patient_id, req.mode, req.start_at, req.speed, owner(request))
        return session_view(s)

    @api.get("/replay/sessions/{session_id}", response_model=ReplaySession, responses=ERRORS)
    def get_session(session_id: str, request: Request):
        s = synced(session_id, request)
        with s.lock:
            return session_view(s)

    @api.post("/replay/sessions/{session_id}/control", response_model=ReplaySession, responses=ERRORS)
    def control(session_id: str, cmd: ControlCommand, request: Request):
        s = state.sessions.control(session_id, cmd.action, cmd.steps, cmd.seek_to, cmd.speed, owner(request))
        with s.lock:
            return session_view(s)

    @api.get("/replay/sessions/{session_id}/events", response_model=EventPage, responses=ERRORS)
    def events(session_id: str, request: Request, cursor: str | None = None,
               limit: int = Query(500, ge=1, le=2000)):
        s = synced(session_id, request)
        with s.lock:
            start = 0
            if cursor:
                try:
                    rev_s, idx_s = cursor.split(".", 1)
                    rev, start = int(rev_s.lstrip("r")), int(idx_s)
                    if start < 0:  # a negative index would count back from the end, past the replay clock
                        raise ValueError(start)
                except ValueError as exc:
                    raise ApiError(422, "invalid_cursor", "Cursor is not valid.") from exc
                if rev != s.revision:
                    raise ApiError(409, "stale_cursor",
                                   "The session was rewound or reset; restart polling from the beginning.")
            released = s.timeline.released_count(s.clock)
            end = min(released, start + limit)
            items = [state.sessions.event_payload(s, s.timeline.order[i]) for i in range(start, end)]
            return {"schema_version": "1.0", "session_id": s.id, "session_revision": s.revision,
                    "clock_at": from_minutes(s.clock), "items": items, "next_cursor": f"r{s.revision}.{end}",
                    "has_more": end < released}

    @api.get("/replay/sessions/{session_id}/profile", response_model=SessionProfile, responses=ERRORS)
    def session_profile(session_id: str, request: Request):
        s = synced(session_id, request)
        with s.lock:
            vals = []
            for a in state.catalog.profile(s.patient_id):
                status, value = a["status"], a.get("value")
                avail = a.get("available_at")
                if status == "available":
                    from glucotwin.data.store import to_minutes
                    if avail is None or float(to_minutes([avail])[0]) > s.clock + 1e-6:
                        status, value = "not_yet_available", None
                elif status == "excluded_suspect":
                    value = None
                vals.append({"name": a["name"], "label": a["label"], "value": value, "unit": a.get("unit"),
                             "source": a.get("source"),
                             "available_at": avail if status == "available" else None, "status": status,
                             "note": a.get("note")})
            return {"schema_version": "1.0", "session_id": s.id, "patient_id": s.patient_id,
                    "session_revision": s.revision, "as_of": from_minutes(s.clock),
                    "cohort": state.catalog.meta(s.patient_id)["cohort"], "values": vals}

    @api.get("/replay/sessions/{session_id}/twin", response_model=TwinState, responses=ERRORS)
    def twin(session_id: str, request: Request):
        s = synced(session_id, request)
        with s.lock:
            return s.engine.twin_state(s.clock, s.timeline.released(s.clock))

    def public(f: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in f.items() if not k.startswith("_")}

    @api.get("/replay/sessions/{session_id}/forecast", response_model=LatestForecast, responses=ERRORS)
    def latest_forecast(session_id: str, request: Request):
        s = synced(session_id, request)
        with s.lock:
            fc = s.engine.forecasts
            base = {"schema_version": "1.0", "session_id": s.id, "session_revision": s.revision,
                    "clock_at": from_minutes(s.clock)}
            if not fc:
                reasons = [{"code": "no_forecast_yet", "message": "No glucose observation has been released yet."}]
                if state.serving.get(s.mode) is None:
                    reasons.append({"code": "model_unavailable",
                                    "message": state.serving_errors.get(s.mode, "Model unavailable.")})
                return {**base, "availability": "not_ready", "age_minutes": None, "reasons": reasons, "forecast": None}
            last = fc[-1]
            age = s.clock - last["_origin"]
            if age > STALE_MINUTES:
                return {**base, "availability": "stale", "age_minutes": round(age, 1),
                        "reasons": [{"code": "stale_forecast",
                                     "message": f"The latest forecast was issued {age:.0f} minutes before the replay "
                                                "clock; no newer glucose reading is available."}],
                        "forecast": public(last)}
            reasons = []
            if last["quality"]["status"] == "insufficient":
                reasons = [{"code": "forecast_insufficient", "message": "The twin abstained at the latest origin."}]
            return {**base, "availability": "available" if not reasons else "not_ready",
                    "age_minutes": round(age, 1), "reasons": reasons, "forecast": public(last)}

    @api.get("/replay/sessions/{session_id}/forecasts", response_model=ForecastPage, responses=ERRORS)
    def forecasts(session_id: str, request: Request, cursor: str | None = None,
                  limit: int = Query(100, ge=1, le=500), order: Literal["asc", "desc"] = "asc"):
        s = synced(session_id, request)
        with s.lock:
            fc = [f for f in s.engine.forecasts if f["_origin"] <= s.clock + 1e-6]
            if order == "desc":
                fc = fc[::-1]
            start = 0
            if cursor:
                try:
                    rev_s, idx_s = cursor.split(".", 1)
                    rev, start = int(rev_s.lstrip("r")), int(idx_s)
                    if start < 0:  # a negative index would count back from the end, past the replay clock
                        raise ValueError(start)
                except ValueError as exc:
                    raise ApiError(422, "invalid_cursor", "Cursor is not valid.") from exc
                if rev != s.revision:
                    raise ApiError(409, "stale_cursor", "The session was rewound or reset; restart paging.")
            page = fc[start:start + limit]
            nxt = f"r{s.revision}.{start + limit}" if start + limit < len(fc) else None
            return {"schema_version": "1.0", "session_id": s.id, "session_revision": s.revision,
                    "clock_at": from_minutes(s.clock), "items": [public(f) for f in page], "next_cursor": nxt,
                    "order": order}

    def alert_view(s: Session, a) -> dict[str, Any]:
        ack = state.store.acknowledgement(a.alert_id)
        srv = s.engine.serving  # the model and warning policy this session was created with (never re-labelled)
        H = srv.alert.get("horizon_minutes") if srv else 60
        return {
            "schema_version": "1.0", "alert_id": a.alert_id, "session_id": s.id, "patient_id": s.patient_id,
            "session_revision": s.revision, "issued_at": from_minutes(a.issued_at),
            "last_supported_at": from_minutes(a.last_supported_at), "horizon_minutes": H,
            "rule_version": srv.alert.get("rule_version"),
            "model_version": srv.model_version, "kind": "predicted_new_high_episode",
            "title": f"Research warning: forecast suggests a new sustained high (>180 mg/dL) within {H} minutes",
            "evidence": a.evidence, "supporting_forecast_ids": a.forecast_ids, "state": a.state,
            "outcome": a.outcome,
            "acknowledgement": {"acknowledged": ack is not None, "acknowledged_at": ack["acknowledged_at"] if ack else None,
                                "note": ack["note"] if ack else None},
        }

    @api.get("/replay/sessions/{session_id}/alerts", response_model=AlertList, responses=ERRORS)
    def alerts(session_id: str, request: Request):
        s = synced(session_id, request)
        with s.lock:
            serving = s.engine.serving
            items = [alert_view(s, a) for a in s.engine.alerts] if serving else []
            desc = None
            if serving:
                al = serving.alert
                desc = (f"Fires when the online state is 'normal' and the highest forecast within "
                        f"{al.get('horizon_minutes')} min exceeds 180 mg/dL by at least "
                        f"{al.get('threshold_margin_mg_dl')} mg/dL (threshold selected on validation data). "
                        f"Firings within {al.get('episode_merge_minutes')} min extend one warning.")
            return {"schema_version": "1.0", "session_id": s.id, "session_revision": s.revision,
                    "clock_at": from_minutes(s.clock), "rule_available": serving is not None,
                    "rule_description": desc, "items": items[::-1]}

    @api.post("/replay/sessions/{session_id}/alerts/{alert_id}/acknowledgement", response_model=Alert,
              responses=ERRORS)
    def acknowledge(session_id: str, alert_id: str, request: Request, req: AcknowledgementRequest | None = None):
        s = synced(session_id, request)  # the caller's own session first: another visitor's alert IDs are unreachable
        with s.lock:
            a = next((x for x in s.engine.alerts if x.alert_id == alert_id), None)
            if a is None:
                raise ApiError(404, "alert_not_found", "No such alert in the current session revision.")
            state.store.acknowledge(alert_id, s.id, req.note if req else None)
            return alert_view(s, a)

    # ------------------------------------------------------------------ evaluation

    def published(name: str, current: dict[str, Any], missing: bool) -> dict[str, Any]:
        """Public demo only: when this installation has no saved artifacts for an evidence endpoint, serve the committed
        aggregate-only snapshot (marked source=published_snapshot) instead. A local installation never reads it."""
        if cfg.enabled and missing:
            snap = snapshot.load(name)
            if snap is not None:
                return snap
        return snapshot.withhold_ids(current) if cfg.enabled else current

    @api.get("/evaluations", response_model=EvaluationList)
    def evaluations():
        rep = evidence.list_experiments()
        return published(snapshot.file_name("evaluations"), rep,
                         not any(i["status"] == "completed" for i in rep["items"]))

    def no_participant_rows(rep: dict[str, Any]) -> dict[str, Any]:
        """Public demo: pooled results only; per-participant rows of recorded-data evaluations are withheld."""
        if not cfg.enabled:
            return rep
        rep = {**rep, "per_patient": []}
        if rep.get("cohort"):  # keep how many were excluded and why, not who (the UI shows the count)
            rep["cohort"] = {**rep["cohort"], "excluded": [{k: v for k, v in x.items() if k != "display_alias"}
                                                           for x in rep["cohort"].get("excluded", [])]}
        rep["optional_experiments"] = [{k: v for k, v in o.items() if k != "results"}
                                       if o.get("results") and any("participant" in r for r in o["results"]
                                                                   if isinstance(r, dict)) else o
                                       for o in rep.get("optional_experiments", [])]
        return rep

    @api.get("/evaluations/latest", response_model=EvaluationReport)
    def evaluation():
        rep = no_participant_rows(build_report())
        return published(snapshot.file_name("evaluations", "latest"), rep, rep["status"] != "completed")

    @api.get("/evaluations/{experiment_id}", response_model=EvaluationReport, responses=ERRORS)
    def evaluation_by_id(experiment_id: str):
        if experiment_id in evidence.RESEARCH_EXPERIMENTS:
            raise ApiError(404, "use_research_endpoint", "This is a nested research experiment; use /research/{id}.")
        rep = build_report(experiment_id)
        if rep["status"] == "not_run":
            snap = published(snapshot.file_name("evaluations", experiment_id), {}, True)
            if snap:
                return snap
            raise ApiError(404, "experiment_not_found", f"No saved metrics for experiment {experiment_id!r}.")
        return no_participant_rows(rep)

    @api.get("/research/{experiment_id}", response_model=ResearchReport, responses=ERRORS)
    def research(experiment_id: str):
        rep = evidence.research_report(experiment_id)
        if rep is None:
            raise ApiError(404, "experiment_not_found", f"Unknown research experiment {experiment_id!r}.")
        return published(snapshot.file_name("research", experiment_id), rep, rep["status"] != "completed")

    @api.get("/research-summaries", response_model=ResearchSummaryList)
    def research_summaries():
        """Headline results of the research run after the demo model was chosen; none of it is the demo model."""
        rep = evidence.research_summaries()
        return published(snapshot.file_name("research_summaries"), rep,
                         all(i["status"] != "available" for i in rep["items"]))

    @api.get("/serving", response_model=ServingList)
    def serving_models():
        return evidence.serving_summaries(state.serving, state.serving_errors)

    @api.get("/datasets", response_model=DatasetInventory)
    def datasets():
        rep = evidence.dataset_inventory()
        return published(snapshot.file_name("datasets"), rep, rep["status"] != "available")

    app.include_router(api)

    dist = os.environ.get("GLUCOTWIN_WEB_DIST")
    if dist:
        root = Path(dist).resolve()
        index = root / "index.html"
        if not index.is_file():
            raise RuntimeError(f"GLUCOTWIN_WEB_DIST={dist!r} has no index.html; build the web app first.")

        @app.get("/{path:path}", include_in_schema=False)
        def web(path: str):
            """The built web app: real files as they are, any other non-API path falls back to the SPA."""
            if path == "api" or path.startswith("api/"):
                raise StarletteHTTPException(404, "Not Found")
            f = (root / path).resolve()
            if path and f.is_file() and f.is_relative_to(root):
                cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
                return FileResponse(f, headers={"Cache-Control": cache})
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()

