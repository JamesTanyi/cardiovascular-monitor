from datetime import datetime

def build_temporal_context(records):
    """
    构建时间上下文，计算记录之间的时间差等。
    records: list of dicts (normalized, containing 'timestamp' string or datetime)
    """
    context = {
        "records": records,
        "gaps": [],
        "last_record_time": None
    }
    
    if not records:
        return context
    
    # Helper to get datetime object
    def _get_dt(r):
        ts = r.get("timestamp") or r.get("datetime")
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                return datetime.now()
        return ts

    # Sort by time
    sorted_recs = sorted(records, key=_get_dt)
    context["records"] = sorted_recs
    if sorted_recs:
        context["last_record_time"] = _get_dt(sorted_recs[-1])

    # Calculate gaps (in hours)
    for i in range(1, len(sorted_recs)):
        t1 = _get_dt(sorted_recs[i-1])
        t2 = _get_dt(sorted_recs[i])
        gap_hours = (t2 - t1).total_seconds() / 3600.0
        context["gaps"].append(gap_hours)
        
    return context

def evaluate_gap_aware_risk(context):
    """
    评估基于时间间隔的风险（例如：很久没测了）。
    返回 0.0 (低风险) - 1.0 (高风险)
    """
    gaps = context.get("gaps", [])
    if not gaps:
        # 如果没有间隔数据（只有1条或0条记录），风险适中
        return 0.1
    
    # 计算平均测量间隔
    avg_gap = sum(gaps) / len(gaps)
    
    # 简单规则：
    # 如果平均间隔 > 72小时 (3天)，认为监控力度不足，风险略增
    if avg_gap > 72:
        return 0.3
    # 如果平均间隔 > 168小时 (1周)，风险更高
    if avg_gap > 168:
        return 0.5
        
    return 0.0