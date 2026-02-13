def render_gap_risk_for_user(tokens: dict) -> str:
    gap_days = int(round(tokens["gap_days"]))
    delta = tokens["delta_sbp"]
    level = tokens["risk_level"]

    if level == "none":
        return f"最近一次测量距离上次约 {gap_days} 天，血压变化不大，目前未见明显风险。"

    if level == "low":
        return f"最近一次测量距离上次约 {gap_days} 天，收缩压升高约 {delta:.0f} mmHg，属于轻度升高，建议 24–48 小时内再次测量。"

    if level == "medium":
        return f"检测到约 {gap_days} 天未测量后，本次收缩压升高约 {delta:.0f} mmHg，属于中度风险，建议 24 小时内复测并联系家庭医生。"

    return f"检测到约 {gap_days} 天未测量后，本次收缩压升高约 {delta:.0f} mmHg，属于较高风险，请尽快联系医生。"

def render_gap_risk_for_doctor(tokens: dict) -> str:
    return (
        f"中断 {tokens['gap_days']:.1f} 天后，新 SBP={tokens['new_sbp']} mmHg，"
        f"较 {tokens['baseline_window']} 稳态均值 {tokens['baseline_sbp']} mmHg 变化 {tokens['delta_sbp']} mmHg，"
        f"gap-aware 评估：{tokens['risk_level']}。"
    )
