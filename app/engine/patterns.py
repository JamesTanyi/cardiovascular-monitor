# app/engine/patterns.py
"""
血压模式分类（Pattern Classification）
- 夜间不降型（Non-dipper）
- 晨峰型（Morning Surge）
- 波动型（Variability）
"""

from typing import List, Dict
from datetime import datetime, time
import numpy as np


# ==========================
# 工具函数：判断是否夜间
# ==========================

def _is_night(dt: datetime):
    return dt.time() < time(6, 0) or dt.time() > time(22, 0)


def _is_morning(dt: datetime):
    return time(5, 0) <= dt.time() <= time(10, 0)


# ==========================
# 1. 夜间不降型（Non-dipper）
# ==========================

def detect_nocturnal_dip(records: List[Dict]):
    """
    计算夜间 vs 白天 SBP 平均值
    夜间下降 < 10% → non-dipper
    """
    day_sbp = []
    night_sbp = []

    for r in records:
        if _is_night(r["datetime"]):
            night_sbp.append(r["sbp"])
        else:
            day_sbp.append(r["sbp"])

    if len(day_sbp) < 3 or len(night_sbp) < 3:
        return "insufficient_data"

    day_mean = np.mean(day_sbp)
    night_mean = np.mean(night_sbp)

    dip_rate = (day_mean - night_mean) / day_mean

    if dip_rate < 0.1:
        return "non-dipper"
    elif dip_rate < 0.2:
        return "reduced-dipper"
    else:
        return "normal-dipper"


# ==========================
# 2. 晨峰型（Morning Surge）
# ==========================

def detect_morning_surge(records: List[Dict]):
    """
    计算晨间 SBP 与夜间最低 SBP 的差值
    > 35 mmHg → 晨峰型
    """
    morning = []
    night = []

    for r in records:
        if _is_morning(r["datetime"]):
            morning.append(r["sbp"])
        if _is_night(r["datetime"]):
            night.append(r["sbp"])

    if not morning or not night:
        return "insufficient_data"

    morning_mean = np.mean(morning)
    night_min = np.min(night)

    surge = morning_mean - night_min

    if surge >= 35:
        return "present"
    elif surge >= 20:
        return "mild"
    else:
        return "absent"


# ==========================
# 3. 波动型（Variability）
# ==========================

def detect_variability(records: List[Dict]):
    """
    使用 SBP 标准差评估波动性：
    SD < 8 → low
    SD < 12 → medium
    SD >= 12 → high
    """
    sbp_values = [r["sbp"] for r in records]

    if len(sbp_values) < 5:
        return "insufficient_data"

    sd = np.std(sbp_values)

    if sd < 8:
        return "low"
    elif sd < 12:
        return "medium"
    else:
        return "high"


# ==========================
# 4. 主入口：返回 pattern_result
# ==========================

def analyze_patterns(records):
    return {
        "nocturnal_dip": detect_nocturnal_dip(records),
        "morning_surge": detect_morning_surge(records),
        "variability": detect_variability(records),
    }
