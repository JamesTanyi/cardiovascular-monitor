from statistics import median
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

METRICS = ["sbp", "dbp", "pp", "hr"]

# 使用“记录数量”作为窗口长度，而不是天数
# 这里的 key 只是标签，不一定真的是天数
WINDOW_SIZES = {
    "3pt": 3,   # 新增：超短窗口，确保测试数据也能出点
    "5pt": 5,   # 原 14w
    "10pt": 10,
    "20pt": 20, # 原 21w
    "30pt": 30, # 原 30w
}

# 综合稳定性权重配置
# 将板块(Segments)分析与血压(BP)、心率(HR)、脉压(PP)结合
METRIC_WEIGHTS = {
    "sbp": 1.0, 
    "dbp": 1.0, 
    "pp": 1.5,  # 脉压差波动对血管稳定性影响大，权重调高
    "hr": 0.8   # 心率天然波动大，权重略低以避免误判
}

def _safe_get_metric_values(records: List[Dict[str, Any]], metric: str) -> List[float]:
    """从记录中安全提取某个指标的数值，过滤掉缺失或 None。"""
    values = []
    for r in records:
        v = r.get(metric)
        if v is not None:
            values.append(v)
    return values


def _compute_profile(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    计算窗口内的中位数、Q1、Q3、IQR。
    这里用分位数来刻画“个人分布”，而不是只看平均值。
    """
    profile: Dict[str, Dict[str, float]] = {}
    n_records = len(records)
    if n_records == 0:
        return profile

    for m in METRICS:
        values = _safe_get_metric_values(records, m)
        values_sorted = sorted(values)
        n = len(values_sorted)
        if n == 0:
            continue

        # 简单分位数估计，避免依赖外部库
        def _percentile(sorted_vals: List[float], p: float) -> float:
            if not sorted_vals:
                return 0.0
            # 使用四舍五入(加0.5取整)来获取最近的索引，避免 N=2 时 Q1=Q3 的问题
            idx = int(p * (len(sorted_vals) - 1) + 0.5)
            return sorted_vals[idx]

        q1 = _percentile(values_sorted, 0.25)
        q3 = _percentile(values_sorted, 0.75)
        iqr = max(q3 - q1, 0.0)

        profile[m] = {
            "median": float(median(values_sorted)),
            "q1": float(q1),
            "q3": float(q3),
            "iqr": float(iqr),
        }
    return profile


def _compute_stability(profile: Dict[str, Dict[str, float]]) -> float:
    """
    稳定性 = 1 / (1 + 加权平均 IQR)
    结合 SBP, DBP, PP, HR 的波动情况进行综合判断。
    """
    if not profile:
        return 0.0

    total_iqr = 0.0
    total_weight = 0.0

    for m in METRICS:
        if m in profile and "iqr" in profile[m]:
            w = METRIC_WEIGHTS.get(m, 1.0)
            total_iqr += profile[m]["iqr"] * w
            total_weight += w

    if total_weight == 0:
        return 0.0

    avg_iqr = total_iqr / total_weight
    stability = 1.0 / (1.0 + avg_iqr)
    return float(stability)


def _sort_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not records:
        return []
    
    def _parse_dt(r):
        dt = r.get("datetime")
        # 如果是字符串，转换为 datetime 对象
        if isinstance(dt, str):
            try:
                return datetime.fromisoformat(dt.replace(" ", "T"))
            except:
                return datetime.min
        return dt if isinstance(dt, datetime) else datetime.min

    return sorted(records, key=_parse_dt)


def _get_max_gap_days(records: List[Dict[str, Any]]) -> float:
    """计算窗口内相邻记录的最大时间间隔（天）"""
    if len(records) < 2:
        return 0.0
    max_gap = 0.0
    for i in range(len(records) - 1):
        t1 = records[i]["datetime"]
        t2 = records[i+1]["datetime"]
        # 确保是 datetime 对象
        if not isinstance(t1, datetime) or not isinstance(t2, datetime):
             continue
        gap = (t2 - t1).total_seconds() / 86400.0
        if gap > max_gap:
            max_gap = gap
    return max_gap

def _slide_windows(records: List[Dict[str, Any]], window_size: int) -> List[Dict[str, Any]]:
    """
    按记录数量滑动窗口。
    每个窗口都计算 profile 和 stability。
    【新增】引入时间-次数互动逻辑：如果窗口内存在过大的时间断层，降低其稳定性评分。
    """
    records = _sort_records(records)
    windows = []
    n = len(records)
    if n < window_size:
        return []

    for start in range(0, n - window_size + 1):
        end = start + window_size
        w_records = records[start:end]
        profile = _compute_profile(w_records)
        stability = _compute_stability(profile)

        # --- 时间-次数互动算法 (Time-Count Interaction) ---
        # 1. 计算窗口内最大时间间隔
        max_gap = _get_max_gap_days(w_records)
        
        # 2. 如果间隔过大（例如超过7天），说明这个“数量窗口”在时间上是不连续的
        #    对其稳定性进行惩罚，使其不被选为基线或近期状态
        if max_gap > 7.0:
            # 惩罚因子：间隔越大，稳定性越低
            # 例如间隔 8天 -> stability / 2
            # 间隔 30天 -> stability / 24
            penalty = 1.0 + (max_gap - 7.0)
            stability = stability / penalty

        windows.append({
            "start_idx": start,
            "end_idx": end,
            "start": records[start]["datetime"],
            "end": records[end - 1]["datetime"],
            "profile": profile,
            "stability": stability,
            "max_gap_days": max_gap, # 记录下来供调试
            "time_span_days": (records[end - 1]["datetime"] - records[start]["datetime"]).total_seconds() / 86400.0 if n > 0 else 0.0
        })

    return windows


def _select_baseline(windows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    选择最稳定的窗口作为 baseline。
    这里的 baseline 代表“个人典型状态”，而不是“绝对正常”。
    """
    return max(windows, key=lambda w: w["stability"])


def _select_recent(windows: List[Dict[str, Any]], baseline: Dict[str, Any]) -> Dict[str, Any]:
    """
    选择最接近末尾且稳定性 >= baseline 50% 的窗口作为“近期状态”。
    这样既不过度敏感，又能反映最近的变化。
    """
    last_time = windows[-1]["end"]
    baseline_stability = baseline["stability"]

    # 按“离末尾的距离”排序
    candidates = sorted(
        windows,
        key=lambda w: abs((last_time - w["end"]).total_seconds())
    )

    # 找到稳定性足够的
    for w in candidates:
        if w["stability"] >= 0.5 * baseline_stability:
            return w

    # 如果都不够稳定，就选最近的那个
    return candidates[0]

def _estimate_user_variability(windows: List[Dict[str, Any]]) -> float:
    """
    【新增】估算用户的个体变异性（噪声水平）。
    取所有原子窗口 IQR 的中位数，加权合成一个“基准波动值”。
    这体现了“个体差异性”：波动大的人，基准值高；波动小的人，基准值低。
    """
    if not windows:
        return 10.0 # 默认兜底值

    iqr_lists = {m: [] for m in METRICS}
    # 权重需与 _segment_states 中的聚类权重保持一致
    weights = METRIC_WEIGHTS

    for w in windows:
        p = w.get("profile", {})
        for m in METRICS:
            if m in p:
                iqr_lists[m].append(p[m]["iqr"])
    
    total_volatility = 0.0
    for m in METRICS:
        vals = iqr_lists[m]
        # 取中位数代表该指标的“典型波动幅度”
        metric_vol = float(median(vals)) if vals else 5.0
        total_volatility += metric_vol * weights.get(m, 1.0)
        
    return total_volatility

def _segment_states(records: List[Dict[str, Any]],
                    windows_base: List[Dict[str, Any]],
                    dynamic_threshold: float = 15.0) -> Tuple[List[Dict[str, Any]],
                                                               List[Dict[str, Any]]]:
    if not windows_base:
        return [], []

    segments = []
    current_seg = None
    
    # --- 核心修复点：确保 weights 在此处定义 ---
    weights = METRIC_WEIGHTS

    for w in windows_base:
        profile = w["profile"]
        if not profile:
            continue

        medians = {m: profile[m]["median"] for m in profile}

        if current_seg is None:
            current_seg = {
                "start": w["start"],
                "end": w["end"],
                "profile_sum": {m: medians[m] for m in medians},
                "count": 1,
            }
            continue

        # 【科学性增强】时间断裂检测
        # 如果当前窗口的开始时间，距离上一段的结束时间超过 7 天，强制切分
        # 这避免了将两个相隔很久但数值相近的时期强行合并
        days_gap = (w["start"] - current_seg["end"]).total_seconds() / 86400.0
        if days_gap > 7.0:
            force_break = True
        else:
            force_break = False

        # 计算当前窗口与当前段“平均中位数”的加权差异
        diff = 0.0
        for m in medians:
            prev_avg = current_seg["profile_sum"].get(m, 0.0) / max(1, current_seg["count"])
            # 此时引用 weights 已经安全了
            diff += abs(medians[m] - prev_avg) * weights.get(m, 1.0)

        # 【改进】使用传入的 dynamic_threshold (自适应阈值)
        # 替代了原本固定的 15.0，实现了“相对稳态”的判定
        if diff < dynamic_threshold and not force_break:
            current_seg["end"] = w["end"]
            for m in medians:
                current_seg["profile_sum"][m] = current_seg["profile_sum"].get(m, 0.0) + medians[m]
            current_seg["count"] += 1
        else:
            segments.append(current_seg)
            current_seg = {
                "start": w["start"],
                "end": w["end"],
                "profile_sum": {m: medians[m] for m in medians},
                "count": 1,
            }

    if current_seg is not None:
        segments.append(current_seg)

    # 计算每段的真实分布特征 (Space & Time Distribution)
    # 不再是简单的平均，而是基于该段内所有原始数据重新计算分布
    final_segments = []
    for seg in segments:
        # 提取该段内的所有原始记录 (基于时间范围)
        seg_records = [r for r in records if seg["start"] <= r["datetime"] <= seg["end"]]
        
        if not seg_records:
            continue
            
        # 重新计算该段的整体分布和稳定性
        seg_profile = _compute_profile(seg_records)
        seg_stability = _compute_stability(seg_profile)
        
        # 【新增】区分“稳态平台” (Platform) 与 “过渡变化” (Change)
        # 判定标准：
        # 1. 样本量：至少包含 5 条记录 (原子窗口大小)
        # 2. 稳定性：stability >= 0.1 (对应平均 IQR <= 9)
        is_platform = False
        if len(seg_records) >= 5 and seg_stability >= 0.1:
            is_platform = True

        final_segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "profile": seg_profile,
            "stability": seg_stability,
            "count": len(seg_records),
            "type": "platform" if is_platform else "change"
        })

    # 过渡期：描述从一个稳态到另一个稳态的“结构变化”
    transitions = []
    for i in range(len(final_segments) - 1):
        from_seg = final_segments[i]
        to_seg = final_segments[i + 1]
        magnitude = {}
        for m in METRICS:
            if m in from_seg["profile"] and m in to_seg["profile"]:
                magnitude[m] = (
                    to_seg["profile"][m]["median"] -
                    from_seg["profile"][m]["median"]
                )
        transitions.append({
            "from_idx": i,
            "to_idx": i + 1,
            "period": {
                "start": from_seg["end"],
                "end": to_seg["start"],
            },
            "magnitude": magnitude,
        })

    return final_segments, transitions


def _events_by_segment(records: List[Dict[str, Any]],
                        segments: List[Dict[str, Any]]) -> List[List[str]]:
    """
    统计每个稳态段内的事件。
    新增补丁：若 segments 为空，则提取最新一条记录的症状，确保高危不漏报。
    """
    results = []
    
    # 1. 正常的逻辑：按稳态分段提取
    for seg in segments:
        seg_symptoms = set()
        for r in records:
            dt = r.get("datetime")
            if dt and seg["start"] <= dt <= seg["end"]:
                evs = r.get("events") or r.get("symptoms") or []
                if isinstance(evs, list):
                    for e in evs:
                        seg_symptoms.add(str(e).lower().strip())
        results.append(list(seg_symptoms))

    # 2. 【核心新增部分】：急性响应补丁
    # 如果没有分段（例如数据少于30条），或者最后一个分段里没抓到最新的症状
    if records:
        latest_rec = records[-1]
        latest_evs = latest_rec.get("events") or latest_rec.get("symptoms") or []
        if isinstance(latest_evs, list) and latest_evs:
            # 标准化最新症状
            latest_evs_clean = [str(e).lower().strip() for e in latest_evs]
            
            if not results:
                # 情况 A: 完全没有分段，直接放入最新症状
                results = [latest_evs_clean]
            else:
                # 情况 B: 有分段，确保最后一段包含了最新发生的症状
                last_seg_set = set(results[-1])
                last_seg_set.update(latest_evs_clean)
                results[-1] = list(last_seg_set)

    print(f"DEBUG >>> 最终分段症状提取结果 (含补丁): {results}")
    return results

def analyze_steady_states(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    主函数：稳态识别 + 分段 + 事件分析。

    输出包括：
    - windows：不同窗口长度下的 baseline / recent
    - trajectory：各指标在不同窗口下的“方向 + 幅度”
    - segments：自动识别的稳态段
    - transitions：稳态段之间的结构变化
    - events_by_segment：每个稳态段内的事件分布
    """
    if not records:
        return {}
        
    records = _sort_records(records)
    windows_result: Dict[str, Any] = {}
    trajectory: Dict[str, List[Dict[str, Any]]] = {m: [] for m in METRICS}

    # -----------------------------
    # 1. 多窗口稳态识别
    # -----------------------------
    for label, size in WINDOW_SIZES.items():
        windows = _slide_windows(records, size)
        if not windows:
            continue

        baseline = _select_baseline(windows)
        recent = _select_recent(windows, baseline)

        windows_result[label] = {
            "baseline": baseline,
            "recent": recent,
        }

        # 轨迹：比较 baseline vs recent 的中位数变化
        for m in METRICS:
            b_profile = baseline["profile"].get(m)
            r_profile = recent["profile"].get(m)
            if not b_profile or not r_profile:
                continue

            b = b_profile["median"]
            r = r_profile["median"]
            delta = r - b

            # 这里的阈值 3 是一个“轻微变化”的经验值，你可以根据数据调整
            if abs(delta) < 3:
                status = "stable"
            else:
                status = "up" if delta > 0 else "down"

            trajectory[m].append({
                "window": label,
                "status": status,
                "delta": delta,
                "baseline": b,
                "recent": r,
            })

    # -----------------------------
    # 2. 稳态分段（基于时空分布聚类）
    # -----------------------------
    # 使用 5pt 小窗口作为“原子”探测单元，而非强制 30 条
    windows_base = _slide_windows(records, WINDOW_SIZES["5pt"])
    
    # 【核心改进】计算个体化阈值
    # 1. 获取用户自身的噪声水平 (User Volatility)
    user_volatility = _estimate_user_variability(windows_base)
    # 2. 设定动态阈值：通常设为噪声水平的 1.5 倍，并限制在合理区间 [8, 25]
    #    这样既能适应个体差异，又防止阈值过高或过低导致分段失效
    seg_threshold = max(8.0, min(user_volatility * 1.5, 25.0))
    
    segments, transitions = _segment_states(records, windows_base, dynamic_threshold=seg_threshold)

    # -----------------------------
    # 3. 事件分布
    # -----------------------------
    events_by_segment = _events_by_segment(records, segments)

    return {
        "windows": windows_result,
        "trajectory": trajectory,
        "segments": segments,
        "transitions": transitions,
        "events_by_segment": events_by_segment,
    }
