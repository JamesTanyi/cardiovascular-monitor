from statistics import median
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

METRICS = ["sbp", "dbp", "pp", "hr"]

# 使用“记录数量”作为窗口长度，而不是天数
# 这里的 key 只是标签，不一定真的是天数
WINDOW_SIZES = {
    "14w": 5,
    "21w": 21,
    "30w": 30,
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
            idx = int(p * (len(sorted_vals) - 1))
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
    稳定性 = 1 / (1 + 平均 IQR)
    IQR 越大，波动越大，稳定性越低。
    """
    if not profile:
        return 0.0

    iqr_values = [profile[m]["iqr"] for m in profile if "iqr" in profile[m]]
    if not iqr_values:
        return 0.0

    avg_iqr = sum(iqr_values) / len(iqr_values)
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


def _slide_windows(records: List[Dict[str, Any]], window_size: int) -> List[Dict[str, Any]]:
    """
    按记录数量滑动窗口。
    每个窗口都计算 profile 和 stability。
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

        windows.append({
            "start_idx": start,
            "end_idx": end,
            "start": records[start]["datetime"],
            "end": records[end - 1]["datetime"],
            "profile": profile,
            "stability": stability,
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

def _segment_states(records: List[Dict[str, Any]],
                    windows_30: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]],
                                                               List[Dict[str, Any]]]:
    if not windows_30:
        return [], []

    segments = []
    current_seg = None
    
    # --- 核心修复点：确保 weights 在此处定义 ---
    weights = {"sbp": 1.0, "dbp": 1.0, "hr": 1.5, "pp": 1.2}

    for w in windows_30:
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

        # 阈值设为 15.0 (考虑到加权后的波动)
        if diff < 15.0 and not force_break:
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

    # 计算每段的平均 profile（只保留 median，后续可扩展）
    final_segments = []
    for seg in segments:
        avg_profile = {
            m: seg["profile_sum"][m] / seg["count"]
            for m in seg["profile_sum"]
        }
        final_segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "profile": {m: {"median": avg_profile[m]} for m in avg_profile},
            # 这里可以以后扩展为“段内稳定性”
            "stability": 1.0,
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
    # 2. 稳态分段（基于 30 条记录窗口）
    # -----------------------------
    windows_30 = _slide_windows(records, WINDOW_SIZES["30w"])
    segments, transitions = _segment_states(records, windows_30)

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
