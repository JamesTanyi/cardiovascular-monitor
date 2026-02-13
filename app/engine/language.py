# app/engine/language.py

from datetime import datetime


# ==========================
# 工具函数
# ==========================

def _fmt(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)


def _describe_delta(delta):
    if abs(delta) < 2:
        return "几乎没有变化"
    elif abs(delta) < 5:
        return f"轻度{'升高' if delta > 0 else '下降'}（约 {abs(delta)} mmHg）"
    else:
        return f"明显{'升高' if delta > 0 else '下降'}（约 {abs(delta)} mmHg）"


def _explain_trend(steady_result):
    """解释 SBP/DBP/PP/HR 的基线→近期变化"""
    windows = steady_result.get("windows", {})
    if "30w" not in windows:
        return []

    base = windows["30w"]["baseline"]["profile"]
    recent = windows["30w"]["recent"]["profile"]

    lines = []
    for m in ["sbp", "dbp", "pp", "hr"]:
        if m not in base or m not in recent:
            continue
        b = base[m]["median"]
        r = recent[m]["median"]
        delta = r - b
        lines.append(f"{m.upper()}：{_describe_delta(delta)}")

    return lines


# ==========================
# 老人版（温和 + 中性）
# ==========================

def _generate_user_text(steady_result, risk_bundle):
    trend_lines = _explain_trend(steady_result)

    chronic = risk_bundle["chronic_tension"]
    acute = risk_bundle["acute_push"]
    acute_level = risk_bundle["acute_risk_level"]
    gap_risk = risk_bundle.get("gap_risk", 0.0)

    # --- 熔断机制：如果是高危/危急，直接输出警告，不再废话 ---
    if acute_level in ("critical", "high"):
        return "【警报】系统检测到您的血压或身体状况存在较高风险。\n请立即停止当前活动，保持静坐或卧床休息。\n请尽快告知家属或联系医生，并出示本报告。"
    # -------------------------------------------------------

    text = []

    text.append("最近你的血压整体情况如下：")
    for line in trend_lines:
        text.append(f"- {line}")

    text.append("")

    # 慢性张力
    if chronic < 0.3:
        text.append("从长期来看，你的血压整体比较平稳。")
    elif chronic < 0.6:
        text.append("从长期来看，你的血压有一点偏高，建议继续保持良好的生活习惯。")
    else:
        text.append("从长期来看，你的血压偏高一些，建议按医生的随访计划继续管理。")

    # 急性推力
    if acute < 0.3:
        text.append("最近一两天血压变化不大，可以按平常节奏生活。")
    elif acute < 0.6:
        text.append("最近一两天血压有些起伏，建议这几天多注意休息。")
    else:
        text.append("最近一两天血压变化比较明显，如果你感觉不舒服，请尽快告诉家人。")

    # 测量频率提示
    if gap_risk >= 0.3:
        text.append("\n【提示】您最近测量的次数较少，建议增加测量频率，以便我们更准确地为您分析。")

    return "\n".join(text)


# ==========================
# 家属版（严谨 + 行动建议）
# ==========================

def _generate_family_text(steady_result, risk_bundle):
    trend_lines = _explain_trend(steady_result)

    chronic = risk_bundle["chronic_tension"]
    acute = risk_bundle["acute_push"]
    acute_level = risk_bundle["acute_risk_level"]
    symptom_level = risk_bundle["symptom_level"]
    gap_risk = risk_bundle.get("gap_risk", 0.0)

    # --- 熔断机制：如果是高危/危急，家属版也要优先预警 ---
    if acute_level in ("critical", "high"):
        return f"【警报】患者当前评估等级为：{acute_level.upper()}。\n检测到高风险指标或症状，请立即关注患者状态，并建议尽快就医排查风险。"
    # -------------------------------------------------------

    text = []

    text.append("老人近期的血压情况：")
    for line in trend_lines:
        text.append(f"- {line}")
    text.append("")

    # 慢性张力
    if chronic < 0.3:
        text.append("从长期基础看，血压整体负担不算重。")
    elif chronic < 0.6:
        text.append("从长期基础看，血压负担中等，属于需要长期管理的状态。")
    else:
        text.append("从长期基础看，血压负担偏重，老人属于心脑血管事件的高危人群之一。")

    # 急性推力
    if acute < 0.3:
        text.append("最近 1–2 天内，血压变化幅度不大。")
    elif acute < 0.6:
        text.append("最近 1–2 天内，血压有一定幅度的波动，建议家属在这几天多留意老人精神状态。")
    else:
        text.append("最近 1–2 天内，血压变化幅度较大，属于需要重点关注的阶段。")

    text.append("")

    # 急性风险分层 + 建议
    if acute_level == "low":
        text.append("综合长期基础和近期变化，目前急性事件风险评估为：较低。建议按原计划随访。")

    elif acute_level == "moderate":
        text.append("综合长期基础和近期变化，目前急性事件风险评估为：中等。建议家属在近期多观察老人精神、活动和说话情况。")

    elif acute_level == "moderate_high":
        text.append("综合长期基础和近期变化，目前急性事件风险评估为：偏高。建议在 1–2 天内安排门诊评估，并携带本记录。")

    else:  # high
        text.append("综合长期基础和近期变化，目前急性事件风险评估为：较高。")
        if symptom_level in ("high", "medium"):
            text.append("建议尽快就医，由医生排查是否存在严重心脑血管事件的可能。")
        else:
            text.append("即使目前没有典型症状，也建议尽快就医，由医生评估当前风险。")

    # 测量频率提示
    if gap_risk >= 0.3:
        text.append("\n【提示】监测数据显示测量间隔较长（平均超过 3 天），建议督促老人保持规律测量。")

    return "\n".join(text)


# ==========================
# 医生版（结构化 + 时间序列）
# ==========================

def _generate_doctor_text(records, steady_result, risk_bundle, figure_paths):
    text = []

    # 时间序列
    text.append("## 时间序列概览")
    if records:
        text.append(f"- 记录起始时间：{_fmt(records[0]['datetime'])}")
        text.append(f"- 最近一次记录：{_fmt(records[-1]['datetime'])}")
        text.append(f"- 总记录数：{len(records)}")
    else:
        text.append("- 无可用记录")
    text.append("")

    # 基线 vs 近期（优先使用 30w 窗口；若不存在则回退）
    base = None
    recent = None
    try:
        win = steady_result.get("windows", {}).get("30w")
        if win:
            base = win.get("baseline")
            recent = win.get("recent")
    except Exception:
        base = None
        recent = None

    if base and recent:
        text.append("## 基线与近期稳态（30w 窗口 ）")
        text.append(f"- 基线区间：{_fmt(base['start'])} → {_fmt(base['end'])}")
        text.append(f"- 近期区间：{_fmt(recent['start'])} → {_fmt(recent['end'])}")
        text.append(f"- 基线稳态稳定性：{base.get('stability', 0.0):.3f}")
        text.append(f"- 近期稳态稳定性：{recent.get('stability', 0.0):.3f}")
        text.append("- 基线中位数：")
        for m, v in base.get("profile", {}).items():
            text.append(f"  - {m.upper()}: {v.get('median', 0.0):.1f}")
        text.append("- 最近中位数：")
        for m, v in recent.get("profile", {}).items():
            text.append(f"  - {m.upper()}: {v.get('median', 0.0):.1f}")
        text.append("")
    else:
        text.append("## 基线与近期稳态（30w 窗口）")
        text.append("- 提示：样本量不足以生成 30w 窗口的基线/近期稳态；使用可用记录进行评估。")
        text.append("")

    # 稳态分段
    text.append("## 稳态分段（全程）")
    for i, seg in enumerate(steady_result.get("segments", [])):
        text.append(f"### 稳态段 {i+1}")
        text.append(f"- 时间：{_fmt(seg['start'])} → {_fmt(seg['end'])}")
        text.append(f"- 稳定性：{seg.get('stability', 0.0):.3f}")
        text.append("- 中位数：")
        for m, v in seg.get("profile", {}).items():
            text.append(f"  - {m.upper()}: {v.get('median', 0.0):.1f}")
        text.append("")

    # 风险评分
    text.append("## 风险评分（供参考，不作诊断）")
    text.append(f"- 慢性张力评分（0–1）：{risk_bundle.get('chronic_tension', 0.0):.2f}")
    text.append(f"- 短期动力学推力（0–1）：{risk_bundle.get('acute_push', 0.0):.2f}")
    text.append(f"- 症状等级：{risk_bundle.get('symptom_level', 'none')}")
    text.append(f"- 急性风险分层：{risk_bundle.get('acute_risk_level', 'low')}")
    text.append(f"- 监测依从性风险（Gap Risk）：{risk_bundle.get('gap_risk', 0.0):.2f}")
    text.append("")

    # 血压模式分析
    patterns = figure_paths.get("patterns", {})
    text.append("## 血压模式分析（Patterns）")
    dip = patterns.get("nocturnal_dip", "N/A")
    surge = patterns.get("morning_surge", "N/A")
    variability = patterns.get("variability", "N/A")
    text.append(f"- 夜间血压下降类型（Nocturnal Dip）：{dip}")
    text.append(f"- 晨峰（Morning Surge）：{surge}")
    text.append(f"- 血压波动性（Variability）：{variability}")
    text.append("")

    # 可视化图表 (嵌入 HTML)
    text.append("## 可视化分析")
    
    if "scatter_url" in figure_paths:
        text.append("### 1. 血压分布与风险分级 (BP Distribution)")
        text.append(f'<img src="{figure_paths["scatter_url"]}" style="width:100%; max-width:600px; border-radius:8px; margin: 10px 0; border:1px solid #eee;">')

    if "time_series_url" in figure_paths:
        text.append("### 2. 血压走势与事件标记 (Time Series)")
        text.append(f'<img src="{figure_paths["time_series_url"]}" style="width:100%; max-width:600px; border-radius:8px; margin: 10px 0; border:1px solid #eee;">')

    return "\n".join(text)


# ==========================
# 主入口
# ==========================

def generate_language_blocks(records, steady_result, risk_bundle, figure_paths):
    return {
        "user": _generate_user_text(steady_result, risk_bundle),
        "family": _generate_family_text(steady_result, risk_bundle),
        "doctor": _generate_doctor_text(records, steady_result, risk_bundle, figure_paths),
    }
