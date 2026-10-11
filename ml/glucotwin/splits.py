"""Chronological within-participant splits with purging.

Raw-time boundaries are fixed per participant from the eligible native-sample span BEFORE any window
or label is constructed:

    [start, train_end)            training            (60 % of elapsed span)
    [train_end, select_end)       validation-selection (first half of the 20 % validation block)
    [select_end, val_end)         validation-calibration (second half)
    [val_end, end]                final test           (20 %)

An origin belongs to a segment when it lies inside the segment AND all of its target/label support
(origin + maximum horizon + confirmation, plus the continuity allowance, and any longer actual label
support) ends before the segment's end. Earlier observations may still provide trailing context to a
later segment; fitted transforms only ever see training rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SEGMENTS = ("training", "validation", "calibration", "test")


@dataclass(frozen=True)
class SplitConfig:
    train_fraction: float = 0.6
    selection_fraction: float = 0.1
    calibration_fraction: float = 0.1
    max_label_support_minutes: float = 75.0   # 60-minute window + 15-minute confirmation
    continuity_allowance_minutes: float = 7.5

    @property
    def purge_minutes(self) -> float:
        return self.max_label_support_minutes + self.continuity_allowance_minutes


@dataclass
class Boundaries:
    start: float
    train_end: float
    select_end: float
    val_end: float
    end: float

    def as_dict(self) -> dict[str, float]:
        return {k: getattr(self, k) for k in ("start", "train_end", "select_end", "val_end", "end")}

    def segment_bounds(self) -> dict[str, tuple[float, float]]:
        return {
            "training": (self.start, self.train_end),
            "validation": (self.train_end, self.select_end),
            "calibration": (self.select_end, self.val_end),
            "test": (self.val_end, self.end + 1e-6),
        }


def boundaries_for(sample_times: np.ndarray, cfg: SplitConfig) -> Boundaries:
    start, end = float(sample_times.min()), float(sample_times.max())
    span = end - start
    train_end = start + cfg.train_fraction * span
    select_end = train_end + cfg.selection_fraction * span
    val_end = select_end + cfg.calibration_fraction * span
    return Boundaries(start, train_end, select_end, val_end, end)


def assign_segments(
    origins: np.ndarray, b: Boundaries, cfg: SplitConfig, support_end: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return (segment label per origin or '', purged flag per origin)."""
    seg = np.full(origins.shape, "", dtype=object)
    purged = np.zeros(origins.shape, dtype=bool)
    for name, (lo, hi) in b.segment_bounds().items():
        inside = (origins >= lo) & (origins < hi)
        ok = inside & (origins + cfg.purge_minutes < hi)
        if support_end is not None:
            ok &= ~(np.isfinite(support_end) & (support_end >= hi))
        seg[ok] = name
        purged |= inside & ~ok
    return seg, purged


def segment_of(t: float, b: Boundaries) -> str:
    for name, (lo, hi) in b.segment_bounds().items():
        if lo <= t < hi:
            return name
    return "unassigned"
