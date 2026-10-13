"""Online, causal GlucoTwin engine for one replay session revision.

The engine is given ONLY events released by the replay clock (``available_at <= clock``); it never
sees the source recording. At each newly available native glucose reading (a forecast origin) it:

1. builds features with ``glucotwin.features.build_features`` (the evaluated transformation),
2. predicts with the serving population model,
3. updates the patient adaptation state (``AdaptationState.step`` — the evaluated protocol),
4. adds conformal intervals and the uncalibrated warning score,
5. updates the online episode state and the research alert rule,
6. issues an immutable forecast record.

Re-running the engine from scratch to the same clock reproduces the same forecasts (replay
equivalence), because every step is deterministic and depends only on released events.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.data.store import PatientData, from_minutes
from glucotwin.evaluation.alerts import match_episodes, qualified_lead
from glucotwin.events import EpisodeMachine, EventDefinition, Onset
from glucotwin.features import QUALITY_MESSAGES, build_features, prepare, profile_unavailable
from glucotwin.models.adaptation import AdaptationState
from glucotwin.serving import ServingModel
from glucotwin.splits import Boundaries, segment_of

NAMESPACE = uuid.UUID("6f1c2b9e-3d4a-4e8b-9a51-0c7d2e1f4b63")

FEATURE_LABELS = {
    "g_last": "latest glucose level", "g_age_min": "age of latest reading",
    "d_15": "change over the last 15 minutes", "d_30": "change over the last 30 minutes",
    "d_60": "change over the last 60 minutes", "slope_15": "15-minute trend", "slope_30": "30-minute trend",
    "slope_60": "60-minute trend", "accel_30": "recent acceleration of the trend",
    "mean_60": "average glucose (60 min)", "std_60": "glucose variability (60 min)",
    "mean_180": "average glucose (3 h)", "std_180": "glucose variability (3 h)", "min_180": "lowest glucose (3 h)",
    "max_180": "highest glucose (3 h)", "frac_high_180": "share of readings above 180 mg/dL (3 h)",
    "n_60": "number of readings (60 min)", "n_180": "number of readings (3 h)", "max_gap_180": "longest gap (3 h)",
    "hist_minutes": "available history", "hr_mean_30": "average heart rate (30 min)",
    "hr_mean_60": "average heart rate (60 min)", "hr_mean_120": "average heart rate (2 h)",
    "mets_mean_30": "average activity (METs, 30 min)", "mets_mean_60": "average activity (METs, 60 min)",
    "mets_max_60": "peak activity (METs, 60 min)", "kcal_sum_60": "activity energy (60 min)",
    "active_min_60": "active minutes (60 min)", "act_cov_60": "wearable coverage (60 min)",
}
for _i in (5, 10, 15, 20, 30, 45, 60, 90, 120):
    FEATURE_LABELS[f"g_lag_{_i}"] = f"glucose {_i} minutes earlier"


def _iso(m: float | None):
    return from_minutes(m) if m is not None and np.isfinite(m) else None


@dataclass
class AlertRecord:
    alert_id: str
    issued_at: float
    last_supported_at: float
    forecast_ids: list[str]
    evidence: dict[str, Any]
    firing_times: list[float] = field(default_factory=list)
    state: str = "open"
    outcome: dict[str, Any] = field(default_factory=lambda: {"status": "pending"})


class TwinEngine:
    def __init__(
        self,
        session_id: str,
        revision: int,
        patient_meta: dict[str, Any],
        serving: ServingModel | None,
        event_def: EventDefinition,
        boundaries: Boundaries | None = None,
        collect_from: float = -np.inf,
    ):
        self.session_id = session_id
        self.revision = revision
        self.meta = patient_meta
        self.patient_id = patient_meta["patient_id"]
        self.mode = patient_meta["mode"]
        self.serving = serving
        self.event_def = event_def
        self.boundaries = boundaries
        self.horizons = serving.horizons if serving else [30, 60]
        self.state = AdaptationState(serving.policy, self.horizons, collect_from) if serving else None
        self.machine = EpisodeMachine(event_def)
        self.machine_ids: list[str] = []
        self.last_origin: float = -np.inf
        self.forecasts: list[dict[str, Any]] = []
        self.alerts: list[AlertRecord] = []
        self.consumed_event_count = 0
        self.gap_times: list[float] = []
        # confirmed onsets persist across updates so matching never depends on which call delivered an onset
        self.confirmed_onsets: list[Onset] = []

    # ------------------------------------------------------------------ helpers

    def _forecast_id(self, origin: float) -> str:
        mv = self.serving.model_version if self.serving else "none"
        return str(uuid.uuid5(NAMESPACE, f"{self.session_id}:{self.revision}:{origin:.6f}:{mv}"))

    def _personalization(self, t: float) -> dict[str, Any]:
        if self.state is None:
            return {"enabled": False, "status": "disabled", "policy_id": None, "state_version": 0, "horizons": []}
        hz = []
        for h in self.horizons:
            s = self.state.horizon_summary(h, t)
            s["last_matured_at"] = _iso(s["last_matured_at"])
            hz.append(s)
        return {"enabled": self.state.policy.enabled, "status": self.state.status(),
                "policy_id": self.state.policy.policy_id, "state_version": self.state.version, "horizons": hz}

    def _sync_machine(self, prep, t: float, onsets_out: list[Onset]) -> None:
        """Feed the episode machine with released samples observed <= t, in observation order."""
        mask = (prep.g_obs <= t + 1e-6) & (prep.g_avail <= t + 1e-6)
        ids = prep.g_ids[mask].tolist()
        if ids[: len(self.machine_ids)] != self.machine_ids:
            # a late-arriving reading was inserted earlier in time: rebuild deterministically
            self.machine = EpisodeMachine(self.event_def)
            self.machine_ids = []
        obs, val = prep.g_obs[mask], prep.g_val[mask]
        for k in range(len(self.machine_ids), len(ids)):
            gap, onset = self.machine.update(float(obs[k]), float(val[k]))
            if gap:
                self.gap_times.append(float(obs[k]))
            if onset is not None:
                onsets_out.append(onset)
            self.machine_ids.append(ids[k])

    # ------------------------------------------------------------------ main loop

    def advance(self, released: PatientData, clock: float) -> list[dict[str, Any]]:
        prep = prepare(released)
        self.consumed_event_count = len(released.glucose) + len(released.activity) + len(released.meals)
        origins = np.unique(prep.g_avail[(prep.g_avail > self.last_origin + 1e-6) & (prep.g_avail <= clock + 1e-6)])
        if origins.size == 0:
            self._update_alert_outcomes(clock, [])
            return []
        issued: list[dict[str, Any]] = []
        spec = self.serving.spec if self.serving else None
        if spec is not None:
            fr = build_features(prep, origins, spec)
            pop = self.serving.predict(fr.frame)
            no_profile = (profile_unavailable(prep, origins, spec) if self.serving.profile_gate
                          else np.zeros(origins.size, dtype=bool))
        else:
            from glucotwin.features import FEATURE_SETS

            fr = build_features(prep, origins, FEATURE_SETS["cgm-only-v1"])
            pop = None
            no_profile = np.zeros(origins.size, dtype=bool)
        for i, t in enumerate(origins.tolist()):
            onsets: list[Onset] = []
            self._sync_machine(prep, t, onsets)
            row = fr.frame.iloc[i]
            q, why = fr.quality[i], fr.reasons[i]
            if no_profile[i]:
                q, why = "insufficient", ["profile_unavailable", *why]
            fid = self._forecast_id(t)
            pop_t = {h: (float(pop[h][i]) if pop is not None and q != "insufficient" else None) for h in self.horizons}
            corr = (self.state.step(t, prep.g_obs, prep.g_val, prep.g_avail, pop_t, fid)
                    if self.state is not None else {h: None for h in self.horizons})
            forecast = self._build_forecast(t, fid, row, q, why, fr.latest_index[i], fr.support_ids[i],
                                            pop_t, corr, prep, released, i, fr)
            self.forecasts.append(forecast)
            issued.append(forecast)
            self._apply_alert_rule(t, forecast)
            self._update_alert_outcomes(t, onsets)
            self.last_origin = t
        self._update_alert_outcomes(clock, [])
        return issued

    # ------------------------------------------------------------------ forecast assembly

    def _build_forecast(self, t, fid, row, quality, reasons, latest_idx, support_ids, pop_t, corr, prep,
                        released, i, fr) -> dict[str, Any]:
        observed = None
        if latest_idx >= 0:
            observed = {"event_id": str(prep.g_ids[latest_idx]), "value_mg_dl": float(prep.g_val[latest_idx]),
                        "observed_at": from_minutes(prep.g_obs[latest_idx]),
                        "available_at": from_minutes(prep.g_avail[latest_idx])}
        estimates, final = [], {}
        if self.serving is None:
            reasons = ["model_unavailable", *reasons]
            quality = "insufficient"
        for h in self.horizons:
            p = pop_t.get(h)
            c = corr.get(h)
            val = None if p is None else p + (c or 0.0)
            final[h] = val
            qh = self.serving.interval_q(h) if self.serving else None
            est = {
                "horizon_minutes": h, "target_at": from_minutes(t + h), "predicted_mg_dl": _r(val),
                "lower_mg_dl": _r(val - qh) if (val is not None and qh is not None) else None,
                "upper_mg_dl": _r(val + qh) if (val is not None and qh is not None) else None,
                "interval_level": self.serving.interval_level if (val is not None and qh is not None) else None,
                "interval_status": "calibrated" if (val is not None and qh is not None) else "unavailable",
                "components": ({"population_mg_dl": _r(p), "patient_correction_mg_dl": _r(c)} if p is not None else None),
            }
            estimates.append(est)
        ep_state = self.machine.public_state
        risks = []
        thr = float(self.event_def.threshold_mg_dl)
        alert_cfg = self.serving.alert if self.serving else {}
        for H in self.horizons:
            vals = [final[h] for h in self.horizons if h <= H and final[h] is not None]
            score = (max(vals) - thr) if vals else None
            if quality == "insufficient" or score is None:
                st = "insufficient"
            elif ep_state == "normal":
                st = "eligible"
            elif ep_state == "pending_high":
                st = "already_high"
            elif ep_state in ("in_episode", "recovering"):
                st = "in_episode"
            else:
                st = "unknown"
            alert_h = alert_cfg.get("horizon_minutes")
            th = alert_cfg.get("threshold_margin_mg_dl") if H == alert_h else None
            risks.append({
                "horizon_minutes": H, "probability": None, "score": _r(score),
                "score_kind": "forecast_margin_mg_dl" if score is not None else "none",
                "score_description": (f"Highest forecast within {H} min minus 180 mg/dL. Uncalibrated research "
                                      "score in mg/dL — not a probability."),
                "state": st, "alert_threshold": th,
                "alert_fired": bool(th is not None and st == "eligible" and score is not None and score >= th),
            })
        explanations = self._explanations(t, row, quality, reasons, released, support_ids, corr, i, fr)
        seg = segment_of(t, self.boundaries) if self.boundaries is not None else None
        return {
            "schema_version": "1.0", "forecast_id": fid, "session_id": self.session_id,
            "patient_id": self.patient_id, "session_revision": self.revision, "as_of": from_minutes(t),
            "mode": self.mode, "model_version": self.serving.model_version if self.serving else None,
            "model_family": self.serving.family if self.serving else None,
            "personalization": self._personalization(t), "observed_glucose": observed, "estimates": estimates,
            "trajectory": None, "event_risk": risks, "episode_state": ep_state,
            "quality": {"status": quality,
                        "reasons": [{"code": r, "message": QUALITY_MESSAGES.get(r, MODEL_MESSAGES.get(r, r))}
                                    for r in reasons]},
            "explanations": explanations, "split_segment": seg,
            "_origin": t,
        }

    def _explanations(self, t, row, quality, reasons, released, support_ids, corr, i, fr) -> list[dict[str, Any]]:
        ex: list[dict[str, Any]] = []
        g = row.get("g_last")
        if np.isfinite(g):
            ex.append({"code": "latest_reading", "kind": "observation",
                       "text": f"Latest reading {g:.0f} mg/dL.", "evidence_event_ids": support_ids[-1:]})
        d30 = row.get("d_30")
        if np.isfinite(d30) and abs(d30) >= 3:
            verb = "rose" if d30 > 0 else "fell"
            ex.append({"code": "trend_30", "kind": "observation",
                       "text": f"Glucose {verb} {abs(d30):.0f} mg/dL over the previous 30 minutes.",
                       "evidence_event_ids": support_ids})
        elif np.isfinite(d30):
            ex.append({"code": "trend_30_flat", "kind": "observation",
                       "text": f"Glucose was approximately stable over the previous 30 minutes ({d30:+.0f} mg/dL).",
                       "evidence_event_ids": support_ids})
        fh = row.get("frac_high_180")
        if np.isfinite(fh) and fh > 0:
            ex.append({"code": "time_above_180", "kind": "observation",
                       "text": f"{fh * 100:.0f}% of readings in the last 3 hours were above 180 mg/dL.",
                       "evidence_event_ids": []})
        if "mets_mean_60" in row.index:
            m60 = row.get("mets_mean_60")
            if np.isfinite(m60) and m60 >= 3.0:
                ex.append({"code": "activity_60", "kind": "observation",
                           "text": f"Wearable summary shows moderate activity in the last hour (mean {m60:.1f} METs).",
                           "evidence_event_ids": []})
        meals = released.meals
        if len(meals):
            recent = meals[(meals["observed_at"] <= from_minutes(t)) &
                           (meals["observed_at"] >= from_minutes(t - 180))]
            if len(recent):
                last = recent.sort_values("observed_at").iloc[-1]
                carbs = last["carbs_g"]
                mins = (pd.Timestamp(from_minutes(t)) - last["observed_at"]).total_seconds() / 60
                carb_txt = f", about {carbs:.0f} g carbohydrate (estimated)" if pd.notna(carbs) else ""
                ex.append({"code": "recent_meal_context", "kind": "observation",
                           "text": f"A {str(last['meal_type']).lower()} was recorded {mins:.0f} minutes earlier"
                                   f"{carb_txt}. Meal records are shown for context; the forecasting model does "
                                   "not use them.", "evidence_event_ids": [str(last["event_id"])]})
        for r in reasons:
            ex.append({"code": f"quality_{r}", "kind": "data_quality",
                       "text": QUALITY_MESSAGES.get(r, MODEL_MESSAGES.get(r, r)), "evidence_event_ids": []})
        if self.state is not None and quality != "insufficient":
            c60 = corr.get(max(self.horizons))
            n = self.state.h[max(self.horizons)].n
            if c60 is not None and n >= self.state.policy.min_residuals and abs(c60) >= 0.5:
                ex.append({"code": "patient_correction", "kind": "personalization",
                           "text": f"Patient adaptation adjusts the {max(self.horizons)}-minute population forecast "
                                   f"by {c60:+.1f} mg/dL, learned from {n} earlier forecast errors for this person.",
                           "evidence_event_ids": []})
            elif n < self.state.policy.min_residuals:
                ex.append({"code": "personalization_warming_up", "kind": "personalization",
                           "text": f"Personalization is warming up ({n} of {self.state.policy.min_residuals} "
                                   "matured forecast errors).", "evidence_event_ids": []})
        if self.serving is not None and quality != "insufficient":
            h = max(self.horizons)
            contrib = self.serving.contributions(fr.frame.iloc[[i]], h)
            if contrib:
                top = [(k, v) for k, v in contrib if abs(v) >= 1.0][:3]
                if top:
                    parts = "; ".join(f"{FEATURE_LABELS.get(k, k)} {v:+.0f} mg/dL" for k, v in top)
                    ex.append({"code": "tree_contributions", "kind": "model_association",
                               "text": f"Largest {h}-minute population-model associations (tree contributions, "
                                       f"not causes): {parts}. The patient correction is reported separately.",
                               "evidence_event_ids": []})
        return ex

    # ------------------------------------------------------------------ alerts

    def _apply_alert_rule(self, t: float, forecast: dict[str, Any]) -> None:
        if self.serving is None:
            return
        H = self.serving.alert.get("horizon_minutes")
        risk = next((r for r in forecast["event_risk"] if r["horizon_minutes"] == H), None)
        if risk is None or not risk["alert_fired"]:
            return
        merge = float(self.serving.alert.get("episode_merge_minutes", 30))
        open_alert = self.alerts[-1] if self.alerts else None
        if open_alert is not None and t - open_alert.last_supported_at <= merge:
            open_alert.last_supported_at = t
            open_alert.forecast_ids.append(forecast["forecast_id"])
            open_alert.firing_times.append(t)
            return
        aid = str(uuid.uuid5(NAMESPACE, f"alert:{self.session_id}:{self.revision}:{t:.6f}"))
        preds = {str(e["horizon_minutes"]): e["predicted_mg_dl"] for e in forecast["estimates"]}
        self.alerts.append(AlertRecord(
            alert_id=aid, issued_at=t, last_supported_at=t, forecast_ids=[forecast["forecast_id"]], firing_times=[t],
            evidence={"forecast_id": forecast["forecast_id"], "score": risk["score"], "score_kind": risk["score_kind"],
                      "threshold": risk["alert_threshold"],
                      "latest_glucose_mg_dl": forecast["observed_glucose"]["value_mg_dl"]
                      if forecast["observed_glucose"] else None,
                      "predicted_mg_dl": preds,
                      "explanation_codes": [e["code"] for e in forecast["explanations"]],
                      "policy_id": self.serving.alert.get("policy_id") or
                      f"{self.serving.config.get('experiment_id')}:{self.serving.alert.get('rule_version')}",
                      "rule_version": self.serving.alert.get("rule_version"),
                      "experiment_id": self.serving.config.get("experiment_id"),
                      "score_units": "mg/dL forecast margin above 180 (uncalibrated; not a probability)",
                      "episode_merge_minutes": merge,
                      "applicability": f"{self.serving.spec.cadence_minutes:g}-minute CGM; recorded-data replay"},
        ))

    def _update_alert_outcomes(self, t: float, onsets: list[Onset]) -> None:
        """Resolve warning outcomes with the SAME one-to-one matcher as the offline evaluation.

        Matching is recomputed from all warnings and all confirmed onsets known so far, so repeated calls, late
        delivery of an onset and replays to the same clock give identical results; a new revision (seek/reset) gets a
        fresh engine. An onset is credited to at most one warning, and a warning becomes a false alarm only after its
        whole follow-up window (H + confirmation + continuity gap) has been observed.
        """
        if self.serving is None:
            return
        known = {o.onset_at for o in self.confirmed_onsets}
        self.confirmed_onsets += [o for o in onsets if o.certain and o.onset_at not in known]
        H = float(self.serving.alert.get("horizon_minutes", 60))
        settle = H + self.event_def.confirm_minutes + self.event_def.max_gap_minutes
        by_time = {o.onset_at: o for o in self.confirmed_onsets}
        hits = match_episodes([(a.issued_at, a.last_supported_at) for a in self.alerts], list(by_time), H)
        for a, hit in zip(self.alerts, hits, strict=True):
            if a.state != "open":
                continue
            if hit is not None:
                o = by_time[hit]
                q, support = qualified_lead(a.firing_times, hit, H)
                a.state = "closed"
                a.outcome = {"status": "onset_observed", "onset_at": from_minutes(o.onset_at),
                             "confirmed_at": from_minutes(o.confirmed_at),
                             "lead_time_minutes": round(o.onset_at - a.issued_at, 1),
                             "episode_start_to_onset_minutes": round(o.onset_at - a.issued_at, 1),
                             "qualified_lead_minutes": None if q is None else round(q, 1),
                             "last_supporting_forecast_at": from_minutes(support) if support is not None else None,
                             "note": "New sustained high-glucose onset confirmed after the warning."}
            elif t > a.last_supported_at + settle:
                gap = any(a.issued_at < g <= a.last_supported_at + settle for g in self.gap_times)
                a.state = "closed"
                a.outcome = ({"status": "unknown", "note": "A sensor gap prevented a definite outcome."} if gap else
                             {"status": "no_onset_observed",
                              "note": f"No new sustained high onset within {int(H)} minutes of the last supporting "
                                      "forecast (counted as a false alarm in evaluation)."})

    # ------------------------------------------------------------------ state view

    def twin_state(self, clock: float, released: PatientData) -> dict[str, Any]:
        prep = prepare(released)
        mask = prep.g_avail <= clock + 1e-6
        obs, vals, ids = prep.g_obs[mask], prep.g_val[mask], prep.g_ids[mask]
        latest = None
        if obs.size:
            latest = {"event_id": str(ids[-1]), "value_mg_dl": float(vals[-1]), "observed_at": from_minutes(obs[-1]),
                      "available_at": from_minutes(prep.g_avail[mask][-1])}
        lb = 180
        in_lb = obs >= clock - lb
        avail_min = float(clock - obs[in_lb][0]) if in_lb.any() else None
        return {
            "schema_version": "1.0", "session_id": self.session_id, "patient_id": self.patient_id,
            "session_revision": self.revision, "as_of": from_minutes(clock),
            "state_version": (self.state.version if self.state else 0) + len(self.forecasts),
            "model_version": self.serving.model_version if self.serving else None,
            "model_family": self.serving.family if self.serving else None,
            "personalization": self._personalization(clock),
            "history": {"lookback_minutes": lb, "available_minutes": _r(avail_min),
                        "valid_samples_lookback": int(in_lb.sum()),
                        "valid_samples_60": int((obs >= clock - 60).sum()), "latest_glucose": latest},
            "episode_state": self.machine.public_state,
            "supporting_event_ids": ids[in_lb][-12:].tolist(),
            "consumed_event_count": self.consumed_event_count,
            "issued_forecast_count": len(self.forecasts),
        }


MODEL_MESSAGES = {"model_unavailable": "No verified forecasting model artifact is loaded for this mode."}


def _r(x: float | None, nd: int = 1) -> float | None:
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return round(xf, nd) if np.isfinite(xf) else None
