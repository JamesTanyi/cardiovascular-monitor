from dataclasses import dataclass
from typing import Optional, Dict
from .temporal_core import TemporalContext

@dataclass
class GapAwareRiskResult:
    gap_category: str
    gap_days: float
    baseline_window: str
    baseline_sbp: Optional[float]
    delta_sbp: Optional[float]
    delta_category: Optional[str]
    risk_level: str
    explanation_tokens: Dict

DELTA_THRESHOLDS = {"small": 10, "moderate": 20, "large": 30}

def _classify_delta(delta: float) -> str:
    d = abs(delta)
    if d < DELTA_THRESHOLDS["small"]:
        return "none"
    elif d < DELTA_THRESHOLDS["moderate"]:
        return "small"
    elif d < DELTA_THRESHOLDS["large"]:
        return "moderate"
    else:
        return "large"

def _select_baseline_window(gap_category: str) -> str:
    if gap_category in ["none", "mild", "moderate"]:
        return "7d"
    return "30d"

def _compute_baseline_sbp(records, start_idx: int, end_idx: int) -> Optional[float]:
    if end_idx - 1 < start_idx:
        return None
    window = records[start_idx:end_idx]
    if not window:
        return None
    return sum(r.sbp for r in window) / len(window)

def _combine_gap_and_delta(gap_cat: str, delta_cat: str) -> str:
    if delta_cat == "none":
        return "none"
    if gap_cat in ["none", "mild"]:
        return {"small": "low", "moderate": "medium", "large": "high"}[delta_cat]
    if gap_cat == "moderate":
        return "medium" if delta_cat == "small" else "high"
    return "medium" if delta_cat == "small" else "high"

def evaluate_gap_aware_risk(tc: TemporalContext) -> Optional[GapAwareRiskResult]:
    if tc.last_record is None or tc.last_gap is None:
        return None

    gap = tc.last_gap
    gap_cat = gap.gap_category
    baseline_window = _select_baseline_window(gap_cat)
    win_idx = tc.window_indices.get(baseline_window)

    baseline_sbp = _compute_baseline_sbp(tc.records, win_idx["start_idx"], win_idx["end_idx"])
    if baseline_sbp is None:
        return None

    new_sbp = tc.last_record.sbp
    delta = new_sbp - baseline_sbp
    delta_cat = _classify_delta(delta)
    risk_level = _combine_gap_and_delta(gap_cat, delta_cat)

    tokens = {
        "gap_days": gap.gap_days,
        "gap_category": gap_cat,
        "baseline_window": baseline_window,
        "baseline_sbp": round(baseline_sbp, 1),
        "new_sbp": round(new_sbp, 1),
        "delta_sbp": round(delta, 1),
        "delta_category": delta_cat,
        "risk_level": risk_level
    }

    return GapAwareRiskResult(
        gap_category=gap_cat,
        gap_days=gap.gap_days,
        baseline_window=baseline_window,
        baseline_sbp=baseline_sbp,
        delta_sbp=delta,
        delta_category=delta_cat,
        risk_level=risk_level,
        explanation_tokens=tokens
    )
