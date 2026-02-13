HIGH_RISK_SYMPTOMS = {"chest_pain", "weakness_one_side", "slurred_speech", "vision_loss", "confusion", "thunderclap_headache"}
MEDIUM_RISK_SYMPTOMS = {"chest_tightness", "dizzy", "palpitations", "short_breath", "severe_headache"}

def assess_risk_bundle(records, steady_data, events_by_segment):
    # 1. 安全检查
    if not records:
        return {"acute_risk_level": "low", "symptom_level": "none"}

    # 2. 增强型数据提取 (处理对象或字典)
    def get_val(obj, key, default=0):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    latest = sorted(records, key=lambda x: get_val(x, 'datetime'))[-1]
    
    # 强制转换数值，防止字符串比较失败
    sbp = float(get_val(latest, 'sbp', 120))
    dbp = float(get_val(latest, 'dbp', 80))
    
    # 提取症状 (兼容多个可能的字段名)
    raw_evs = get_val(latest, 'events', []) or get_val(latest, 'symptoms', [])
    current_symptoms = [str(e).lower().strip() for e in raw_evs] if isinstance(raw_evs, list) else []

    # 3. 提取基线 (稳态分析结果)
    # 注意：这里需要确认 steady_data 的确切结构
    base_info = get_val(steady_data, 'base', {})
    base_sbp = get_val(base_info, 'sbp', None)
    if base_sbp is None: base_sbp = 120.0 # 默认值防止报错
    is_stable = get_val(steady_data, 'is_stable', False)

    # --- 核心判定逻辑 ---
    risk_level = "low"
    reasons = []

    # 准则 1: 症状判定 (验证阶段 5)
    has_high_risk = any(s in HIGH_RISK_SYMPTOMS for s in current_symptoms)
    has_med_risk = any(s in MEDIUM_RISK_SYMPTOMS for s in current_symptoms)

    if has_high_risk:
        risk_level = "critical"
        reasons.append("high_risk_symptoms")
    
    # 准则 2: 绝对数值 (验证阶段 4: 175/108)
    elif sbp >= 170 or dbp >= 105:
        risk_level = "high"
        reasons.append("threshold_violation")

    # 准则 3 & 4: 基线相关判定 (验证阶段 2 & 3)
    elif base_sbp:
        deviation = (sbp - base_sbp) / base_sbp
        if abs(deviation) >= 0.20:
            risk_level = "high" if deviation > 0 else "moderate"
            reasons.append("baseline_deviation")
        elif base_sbp >= 150 and sbp <= 115:
            risk_level = "high"
            reasons.append("hypoperfusion_risk")

    # 兜底症状
    if risk_level == "low" and has_med_risk:
        risk_level = "moderate"
        reasons.append("med_risk_symptoms")

    # 打印调试信息，看看到底读到了什么
    print(f"DEBUG_RISK >>> SBP:{sbp} Base:{base_sbp} Syms:{current_symptoms} -> Final:{risk_level}")

    # --- 计算评分 (不再硬编码) ---
    # 1. 慢性张力: 基于基线 SBP
    chronic_tension = 0.1
    if base_sbp >= 160: chronic_tension = 0.9
    elif base_sbp >= 140: chronic_tension = 0.6
    elif base_sbp >= 130: chronic_tension = 0.4

    # 2. 急性推力: 基于趋势
    trend_info = get_val(steady_data, 'trend', {})
    sbp_trend = get_val(trend_info, 'sbp', 'stable')
    acute_push = 0.1
    if sbp_trend == "up": acute_push = 0.7
    elif sbp_trend == "down": acute_push = 0.2

    return {
        "acute_risk_level": risk_level,
        "assessment_reasons": reasons,
        "symptom_level": "high" if has_high_risk else ("medium" if has_med_risk else "none"),
        "chronic_tension": chronic_tension,
        "acute_push": acute_push,
        "metrics": {"deviation": 0} # 占位
    }