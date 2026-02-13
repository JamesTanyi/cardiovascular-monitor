from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional

@dataclass
class BPRecord:
    timestamp: datetime
    sbp: float
    dbp: float
    hr: Optional[float] = None

@dataclass
class GapInfo:
    gap_hours: float
    gap_category: str
    gap_days: float

@dataclass
class TemporalContext:
    records: List[BPRecord]
    last_record: Optional[BPRecord]
    last_gap: Optional[GapInfo]
    window_indices: Dict[str, Dict[str, int]]

GAP_THRESHOLDS_DAYS = {
    "mild": 3,
    "moderate": 7,
    "heavy": 14,
    "severe": 30
}

def classify_gap(days: float) -> str:
    if days <= GAP_THRESHOLDS_DAYS["mild"]:
        return "none"
    elif days <= GAP_THRESHOLDS_DAYS["moderate"]:
        return "mild"
    elif days <= GAP_THRESHOLDS_DAYS["heavy"]:
        return "moderate"
    elif days <= GAP_THRESHOLDS_DAYS["severe"]:
        return "heavy"
    else:
        return "severe"

def build_temporal_context(normalized_records: List[Dict]) -> TemporalContext:
    records = [
        BPRecord(
            timestamp=r["timestamp"],
            sbp=r["sbp"],
            dbp=r["dbp"],
            hr=r.get("hr")
        )
        for r in normalized_records
    ]

    if not records:
        return TemporalContext([], None, None, {})

    last_record = records[-1]
    last_gap = _compute_last_gap(records)
    window_indices = _compute_windows(records, last_record.timestamp)

    return TemporalContext(records, last_record, last_gap, window_indices)

def _compute_last_gap(records: List[BPRecord]) -> Optional[GapInfo]:
    if len(records) < 2:
        return None
    last = records[-1]
    prev = records[-2]
    delta = last.timestamp - prev.timestamp
    gap_hours = delta.total_seconds() / 3600
    gap_days = gap_hours / 24
    return GapInfo(gap_hours, classify_gap(gap_days), gap_days)

def _compute_windows(records: List[BPRecord], ref_time: datetime) -> Dict[str, Dict[str, int]]:
    windows_days = {"7d": 7, "14d": 14, "30d": 30}
    window_indices = {}

    for key, days in windows_days.items():
        start_time = ref_time - timedelta(days=days)
        start_idx = 0
        end_idx = len(records) - 1

        for i, r in enumerate(records):
            if r.timestamp >= start_time:
                start_idx = i
                break

        window_indices[key] = {"start_idx": start_idx, "end_idx": end_idx}

    return window_indices
