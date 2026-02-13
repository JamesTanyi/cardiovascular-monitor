# app/engine/timeline.py
"""
事件时间轴（Event Timeline）
整合：
- 血压记录
- 稳态段切换
- 动力学事件（emergency）
- 症状事件（symptoms）
- 风险等级（risk_bundle）
"""

from typing import List, Dict
from datetime import datetime


# ==========================
# 1. 血压事件
# ==========================

def _bp_events(records: List[Dict]):
    events = []
    for r in records:
        events.append({
            "time": r["datetime"],
            "type": "bp",
            "sbp": r["sbp"],
            "dbp": r["dbp"],
            "pp": r["pp"],
            "hr": r["hr"],
            "desc": f"血压记录：{r['sbp']}/{r['dbp']} mmHg，PP={r['pp']}"
        })
    return events


# ==========================
# 2. 稳态段切换事件
# ==========================

def _steady_state_events(steady_result):
    events = []
    for i, seg in enumerate(steady_result.get("segments", [])):
        events.append({
            "time": seg["start"],
            "type": "steady_start",
            "segment": i + 1,
            "desc": f"进入稳态段 {i+1}（稳定性={seg['stability']:.2f}）"
        })
    return events


# ==========================
# 3. 动力学事件（来自 emergency.py）
# ==========================

def _emergency_events(emergency_result, records):
    events = []
    latest = records[-1]

    if emergency_result["emergency"]:
        events.append({
            "time": latest["datetime"],
            "type": "acute_event",
            "desc": "检测到急性动力学事件（短期血压变化显著）",
            "details": emergency_result
        })

    return events


# ==========================
# 4. 症状事件（来自 symptoms.py）
# ==========================

def _symptom_events(events_by_segment, records):
    events = []
    if not events_by_segment:
        return events

    latest = records[-1]
    symptoms = events_by_segment[-1]

    if symptoms:
        events.append({
            "time": latest["datetime"],
            "type": "symptom",
            "symptoms": list(symptoms.keys()),
            "desc": "出现症状：" + "、".join(symptoms.keys())
        })

    return events


# ==========================
# 5. 风险等级事件（来自 risk_bundle）
# ==========================

def _risk_events(risk_bundle, records):
    latest = records[-1]
    return [{
        "time": latest["datetime"],
        "type": "risk",
        "risk_level": risk_bundle["acute_risk_level"],
        "desc": f"急性风险等级：{risk_bundle['acute_risk_level']}"
    }]


# ==========================
# 6. 主入口：生成时间轴
# ==========================

def build_timeline(records, steady_result, emergency_result, events_by_segment, risk_bundle):
    timeline = []

    timeline += _bp_events(records)
    timeline += _steady_state_events(steady_result)
    timeline += _emergency_events(emergency_result, records)
    timeline += _symptom_events(events_by_segment, records)
    timeline += _risk_events(risk_bundle, records)

    # 按时间排序
    timeline.sort(key=lambda x: x["time"])

    return timeline
