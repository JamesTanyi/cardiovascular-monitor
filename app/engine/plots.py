# app/engine/plots.py

import os
import io
import base64
import matplotlib
# 设置非交互式后端，防止在服务器上报错
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from typing import List, Dict
from datetime import datetime, timedelta, time

# --- 修复中文乱码 ---
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS', 'WenQuanYi Micro Hei']
plt.rcParams['axes.unicode_minus'] = False
# ------------------

def plot_time_series(records, steady_result, emergency_result, events_by_segment, output_dir=None):
    """
    增强版血压时间序列图：
    - SBP/DBP 折线
    - 稳态段背景色 (动态分段可视化)
    - 急性动力学事件（红点）
    - 症状事件（黄点）
    """

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "time_series_marked.png")

    times = [r["datetime"] for r in records]
    sbp = [r["sbp"] for r in records]
    dbp = [r["dbp"] for r in records]

    fig, ax = plt.subplots(figsize=(10, 5))

    # ==========================
    # 0. 绘制夜间/晨峰时段背景
    # ==========================
    if times:
        start_date = times[0].date()
        end_date = times[-1].date()
        
        current_date = start_date
        first_iter = True
        while current_date <= end_date:
            # Night period (from 22:00 today to 06:00 tomorrow)
            night_start = datetime.combine(current_date, time(22, 0))
            night_end = datetime.combine(current_date + timedelta(days=1), time(6, 0))
            ax.axvspan(night_start, night_end, color="#E8EAF6", alpha=0.4, zorder=0, 
                       label="夜间时段 (22:00-06:00)" if first_iter else None)

            # Morning period (05:00 to 10:00 today)
            morning_start = datetime.combine(current_date, time(5, 0))
            morning_end = datetime.combine(current_date, time(10, 0))
            ax.axvspan(morning_start, morning_end, color="#FFF9C4", alpha=0.5, zorder=0,
                       label="晨峰时段 (05:00-10:00)" if first_iter else None)

            first_iter = False
            current_date += timedelta(days=1)

    # ==========================
    # 1. 绘制 SBP/DBP 折线
    # ==========================
    ax.plot(times, sbp, label="SBP", color="#E53935", linewidth=2)
    ax.plot(times, dbp, label="DBP", color="#1E88E5", linewidth=2)

    # ==========================
    # 1.1 绘制高血压阈值线
    # ==========================
    ax.axhline(y=140, color="#FF9800", linestyle="--", linewidth=1.5, alpha=0.8, label="高血压阈值 (140)")

    # ==========================
    # 2. 稳态段背景色
    # ==========================
    segments = steady_result.get("segments", [])
    # 交替背景色，区分相邻段
    bg_colors = ["#E0E0E0", "#D0D0D0"]
    
    for i, seg in enumerate(segments):
        # 1. 背景色块
        # 【新增】根据段类型显示不同颜色
        if seg.get("type") == "change":
            seg_color = "#FFF3E0" # 浅橙色表示过渡/变化
            seg_alpha = 0.4
        else:
            seg_color = bg_colors[i % 2] # 灰色表示稳态平台
            seg_alpha = 0.2

        ax.axvspan(seg["start"], seg["end"], color=seg_color, alpha=seg_alpha)
        
        # 2. 绘制该段的中位数水平线 (Steady Level)
        if "profile" in seg:
            sbp_med = seg["profile"].get("sbp", {}).get("median")
            dbp_med = seg["profile"].get("dbp", {}).get("median")
            
            if sbp_med:
                ax.hlines(y=sbp_med, xmin=seg["start"], xmax=seg["end"], colors="#D32F2F", linestyles=":", alpha=0.6)
            if dbp_med:
                ax.hlines(y=dbp_med, xmin=seg["start"], xmax=seg["end"], colors="#1976D2", linestyles=":", alpha=0.6)
                
            # 3. 添加文本标注：段号、样本量(N)、稳定性
            mid_time = seg["start"] + (seg["end"] - seg["start"]) / 2
            count = seg.get("count", 0)
            stability = seg.get("stability", 0.0)
            seg_type = seg.get("type", "unk")[0].upper() # P or C
            
            label_text = f"S{i+1}({seg_type})\nN={count}\nStab={stability:.2f}"
            
            # 放置在 SBP 中位数上方，带半透明背景防止遮挡
            if sbp_med:
                ax.text(mid_time, sbp_med + 5, label_text, 
                        ha='center', va='bottom', fontsize=8, 
                        color='#424242', backgroundcolor='#ffffff80')

    # ==========================
    # 2.1 绘制稳态平台变化连线 (Platform Trend)
    # ==========================
    # 连接各个稳态段的中位数点，形成趋势线，直观展示结构性变化
    plat_times = []
    plat_sbp = []
    plat_dbp = []
    
    # 新增：用于绘制置信区间 (IQR) 的列表
    plat_sbp_q1 = []
    plat_sbp_q3 = []
    plat_dbp_q1 = []
    plat_dbp_q3 = []

    for seg in segments:
        if "profile" in seg:
            mid = seg["start"] + (seg["end"] - seg["start"]) / 2
            
            sbp_prof = seg["profile"].get("sbp", {})
            dbp_prof = seg["profile"].get("dbp", {})
            
            s = sbp_prof.get("median")
            d = dbp_prof.get("median")
            
            if s is not None and d is not None:
                plat_times.append(mid)
                plat_sbp.append(s)
                plat_dbp.append(d)
                
                # 提取 Q1/Q3 用于绘制阴影
                plat_sbp_q1.append(sbp_prof.get("q1", s))
                plat_sbp_q3.append(sbp_prof.get("q3", s))
                plat_dbp_q1.append(dbp_prof.get("q1", d))
                plat_dbp_q3.append(dbp_prof.get("q3", d))
    
    if len(plat_times) > 1:
        # 绘制置信区间阴影 (IQR Range)
        ax.fill_between(plat_times, plat_sbp_q1, plat_sbp_q3, color="#4A148C", alpha=0.15)
        ax.fill_between(plat_times, plat_dbp_q1, plat_dbp_q3, color="#0D47A1", alpha=0.15)

        ax.plot(plat_times, plat_sbp, color="#4A148C", linestyle="--", linewidth=2, alpha=0.7, label="稳态趋势 (SBP)")
        ax.plot(plat_times, plat_dbp, color="#0D47A1", linestyle="--", linewidth=2, alpha=0.7, label="稳态趋势 (DBP)")

    # ==========================
    # 3. 急性动力学事件（红点）
    # ==========================
    if emergency_result["emergency"]:
        latest = records[-1]
        ax.scatter(
            latest["datetime"],
            latest["sbp"],
            color="#D32F2F",
            s=120,
            zorder=5,
            label="急性动力学事件"
        )

    # ==========================
    # 4. 症状事件（黄点）
    # ==========================
    if events_by_segment and events_by_segment[-1]:
        latest = records[-1]
        ax.scatter(
            latest["datetime"],
            latest["dbp"],
            color="#FFC107",
            s=120,
            zorder=5,
            label="症状事件"
        )

    # ==========================
    # 5. 图形美化
    # ==========================
    ax.set_title("血压时间序列（含事件标注）", fontsize=14)
    ax.set_ylabel("血压 (mmHg)")
    
    # --- 增强图例 (Legend) ---
    # 获取已有的 handles (SBP, DBP, Threshold, Night, Morning, Events...)
    handles, labels = ax.get_legend_handles_labels()
    # 添加稳态分段的图例说明
    handles.append(patches.Patch(facecolor='#E0E0E0', alpha=0.2, label='稳态平台 (Platform)'))
    handles.append(patches.Patch(facecolor='#FFF3E0', alpha=0.4, label='过渡变化 (Change)'))
    ax.legend(handles=handles, loc='best')
    ax.grid(alpha=0.3)

    plt.tight_layout()
    
    if output_dir:
        plt.savefig(path, dpi=150)
        plt.close()
        return path
    else:
        # 内存模式 (Base64)
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        plt.close()
        buf.seek(0)
        data = base64.b64encode(buf.read()).decode('utf-8')
        return f"data:image/png;base64,{data}"


def plot_volatility_trend(steady_result: Dict, output_dir: str = None) -> str:
    """
    绘制血压波动性(IQR)的基线 vs 近期对比图 (Multi-Window Volatility)
    替代原本的时间序列波动图，以提供更明确的"状态变化"视角。
    """
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "volatility_trend.png")

    windows = steady_result.get("windows", {})
    if not windows:
        return ""

    # 窗口排序规则
    window_order = {"3pt": 3, "5pt": 5, "10pt": 10, "20pt": 20, "30pt": 30}
    
    # 收集可用窗口
    available_windows = [w for w in windows.keys() if w in window_order]
    if not available_windows:
        return ""
        
    sorted_windows = sorted(available_windows, key=lambda w: window_order.get(w, 999))
    x_map = {w: i for i, w in enumerate(sorted_windows)}

    fig, ax = plt.subplots(figsize=(10, 6))
    
    # 颜色定义 (保持一致性)
    colors = {
        'sbp': '#E53935', # Red
        'dbp': '#1E88E5', # Blue
    }
    
    plotted_something = False
    
    # 绘制 SBP 和 DBP 的波动性对比
    for metric in ['sbp', 'dbp']:
        xs = []
        recents = []
        baselines = []
        
        for w in sorted_windows:
            win_data = windows[w]
            # 安全获取 IQR
            base_profile = win_data.get("baseline", {}).get("profile", {}).get(metric, {})
            recent_profile = win_data.get("recent", {}).get("profile", {}).get(metric, {})
            
            b_iqr = base_profile.get("iqr")
            r_iqr = recent_profile.get("iqr")
            
            if b_iqr is not None and r_iqr is not None:
                xs.append(x_map[w])
                baselines.append(b_iqr)
                recents.append(r_iqr)
        
        if not xs:
            continue
            
        c = colors.get(metric, 'black')
        
        # 绘制 Recent (实线)
        ax.plot(xs, recents, marker='o', linestyle='-', color=c, linewidth=2, label=f"{metric.upper()} Recent IQR")
        
        # 绘制 Baseline (虚线)
        ax.plot(xs, baselines, marker='x', linestyle='--', color=c, alpha=0.5, linewidth=1.5, label=f"{metric.upper()} Baseline IQR")
        
        # 绘制变化箭头
        for x, b, r in zip(xs, baselines, recents):
            # 只有变化明显(>=1.0)才画箭头，避免杂乱
            if abs(r - b) >= 1.0: 
                ax.annotate('', xy=(x, r), xytext=(x, b),
                            arrowprops=dict(arrowstyle='->', color=c, alpha=0.6, lw=1.5))
                # 标注差值
                ax.text(x + 0.05, (r + b) / 2, f"{r-b:+.1f}", color=c, fontsize=8, va='center', fontweight='bold')
        
        plotted_something = True

    if not plotted_something:
        plt.close()
        return ""

    # 设置 X 轴
    ax.set_xticks(range(len(sorted_windows)))
    ax.set_xticklabels(sorted_windows)
    ax.set_xlabel("Observation Window Size (Sensitivity)")
    
    ax.set_ylabel("Volatility (IQR, mmHg)")
    ax.set_title("多窗口波动性分析 (Multi-Window Volatility)\n(Solid: Recent, Dashed: Baseline)")
    
    # 添加说明栏
    explanation = "说明：展示不同观察窗口下血压波动性(IQR)的变化。\n" \
                  "实线代表近期波动，虚线代表基线波动。\n" \
                  "IQR越大，代表血压越不稳定。"
    plt.figtext(0.5, 0.01, explanation, ha="center", fontsize=9, 
                bbox={"facecolor":"#FFF9C4", "alpha":0.5, "pad":5, "edgecolor":"#E0E0E0"})
    
    plt.subplots_adjust(bottom=0.18)
    
    ax.legend(loc='best', fontsize='small', ncol=2)
    ax.grid(True, linestyle='--', alpha=0.3)
    
    # 确保 Y 轴从 0 开始，因为 IQR 总是非负的
    ax.set_ylim(bottom=0)

    plt.tight_layout()

    if output_dir:
        plt.savefig(path, dpi=150)
        plt.close()
        return path
    else:
        # 内存模式 (Base64)
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        plt.close()
        buf.seek(0)
        data = base64.b64encode(buf.read()).decode('utf-8')
        return f"data:image/png;base64,{data}"


def plot_bp_scatter(records: List[Dict], output_dir: str = None) -> str:
    """
    绘制血压分布散点图 (SBP vs DBP)
    背景带有高血压分级色块，模拟“热力分布”效果。
    """
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "bp_scatter.png")

    sbp = [r["sbp"] for r in records]
    dbp = [r["dbp"] for r in records]

    fig, ax = plt.subplots(figsize=(8, 8))

    # ==========================
    # 1. 绘制背景分级区域 (参考 AHA/ESC 指南)
    # ==========================
    # 正常 (Green): SBP < 120 & DBP < 80
    ax.add_patch(patches.Rectangle((0, 0), 80, 120, color='#4CAF50', alpha=0.15, label='正常'))
    # 升高 (Yellow): SBP 120-129 & DBP < 80
    ax.add_patch(patches.Rectangle((0, 120), 80, 10, color='#FFEB3B', alpha=0.15, label='升高'))
    # 1级高血压 (Orange): SBP 130-139 OR DBP 80-89
    # 这里的矩形覆盖逻辑稍微简化，为了视觉清晰，画大背景
    ax.add_patch(patches.Rectangle((0, 130), 120, 100, color='#FF9800', alpha=0.1, label='高血压'))
    ax.add_patch(patches.Rectangle((80, 0), 40, 230, color='#FF9800', alpha=0.1))
    # 2级/危象 (Red): SBP >= 140 OR DBP >= 90
    ax.add_patch(patches.Rectangle((0, 140), 200, 100, color='#F44336', alpha=0.1, label='2级/危象'))
    ax.add_patch(patches.Rectangle((90, 0), 110, 240, color='#F44336', alpha=0.1))

    # ==========================
    # 2. 绘制散点
    # ==========================
    # 使用半透明点，重叠处颜色加深，形成“热力图”效果
    ax.scatter(dbp, sbp, color='#1976D2', alpha=0.6, s=80, edgecolors='white')

    # 标记最新点
    if sbp:
        ax.scatter(dbp[-1], sbp[-1], color='#D32F2F', s=120, edgecolors='black', label='最新测量', zorder=10)

    # ==========================
    # 3. 设置坐标轴与标签
    # ==========================
    ax.set_xlim(40, 130)
    ax.set_ylim(80, 220)
    ax.set_xlabel("舒张压 (DBP) mmHg", fontsize=12)
    ax.set_ylabel("收缩压 (SBP) mmHg", fontsize=12)
    ax.set_title("血压分布与风险分级图", fontsize=14)
    
    ax.grid(True, linestyle='--', alpha=0.5)
    
    plt.tight_layout()
    
    if output_dir:
        plt.savefig(path, dpi=150)
        plt.close()
        return path
    else:
        # 内存模式 (Base64)
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        plt.close()
        buf.seek(0)
        data = base64.b64encode(buf.read()).decode('utf-8')
        return f"data:image/png;base64,{data}"


def plot_baseline_vs_recent(steady_result: Dict, output_dir: str = None) -> str:
    """生成基线 vs 最近稳态中位数对比条形图"""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "baseline_vs_recent.png")

    windows = steady_result.get("windows", {})
    if not windows:
        return ""

    labels = []
    baseline_vals = {"sbp": [], "dbp": [], "pp": [], "hr": []}
    recent_vals = {"sbp": [], "dbp": [], "pp": [], "hr": []}

    for label, win in windows.items():
        labels.append(label)
        for m in baseline_vals.keys():
            baseline_vals[m].append(win["baseline"]["profile"][m]["median"])
            recent_vals[m].append(win["recent"]["profile"][m]["median"])

    x = range(len(labels))
    width = 0.15

    plt.figure(figsize=(10, 6))
    for i, m in enumerate(baseline_vals.keys()):
        plt.bar([xi + (i - 1.5) * width for xi in x],
                baseline_vals[m], width=width, label=f"{m.upper()} baseline")
        plt.bar([xi + (i - 1.5) * width + width for xi in x],
                recent_vals[m], width=width, label=f"{m.upper()} recent")

    plt.xticks(list(x), labels)
    plt.xlabel("Window")
    plt.ylabel("Median Value")
    plt.title("Baseline vs Recent Medians")
    plt.legend(fontsize=8)
    plt.tight_layout()

    if output_dir:
        plt.savefig(path, dpi=150)
        plt.close()
        return path
    else:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        plt.close()
        buf.seek(0)
        data = base64.b64encode(buf.read()).decode('utf-8')
        return f"data:image/png;base64,{data}"


def plot_trajectory(steady_result: Dict, output_dir: str = None) -> str:
    """生成多时间尺度轨迹图"""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "trajectory.png")

    trajectory = steady_result.get("trajectory", {})
    if not trajectory:
        return ""

    plt.figure(figsize=(10, 6))
    fig, ax = plt.subplots(figsize=(10, 6))

    # 窗口排序规则 (确保 X 轴按窗口大小递增排列)
    window_order = {"3pt": 3, "5pt": 5, "10pt": 10, "20pt": 20, "30pt": 30}

    # 1. 收集并排序所有出现的窗口，确保X轴对齐
    all_windows = set()
    for steps in trajectory.values():
        for s in steps:
            all_windows.add(s["window"])
    
    if not all_windows:
        return ""

    sorted_windows = sorted(list(all_windows), key=lambda w: window_order.get(w, 999))
    x_map = {w: i for i, w in enumerate(sorted_windows)}

    # 强制显示的指标 (保证图表一致性)
    force_show = {'sbp', 'dbp'}
    
    # 颜色定义
    colors = {
        'sbp': '#E53935', # Red
        'dbp': '#1E88E5', # Blue
        'hr': '#43A047',  # Green
        'pp': '#8E24AA'   # Purple
    }

    plotted_something = False
    for m, steps in trajectory.items():
        if not steps:
            continue

        # 过滤逻辑：如果是主要指标(SBP/DBP)，或者有显著变化(>=0.1)，则绘制
        deltas = [s["delta"] for s in steps]
        is_significant = any(abs(d) >= 0.1 for d in deltas)
        if m not in force_show and not is_significant:
            continue

        # 按窗口大小排序当前指标的数据
        sorted_steps = sorted(steps, key=lambda s: window_order.get(s["window"], 999))
        
        xs = [x_map[s["window"]] for s in sorted_steps]
        recents = [s["recent"] for s in sorted_steps]
        baselines = [s["baseline"] for s in sorted_steps]
        
        c = colors.get(m, 'black')
        
        # 绘制 Recent (实线) - 代表当前轨迹
        ax.plot(xs, recents, marker='o', linestyle='-', color=c, linewidth=2, label=f"{m.upper()} Recent")
        
        # 绘制 Baseline (虚线) - 代表参考基准
        ax.plot(xs, baselines, marker='x', linestyle='--', color=c, alpha=0.5, linewidth=1.5, label=f"{m.upper()} Baseline")
        
        # 绘制变化箭头 (从基线指向近期)
        for x, b, r in zip(xs, baselines, recents):
            if abs(r - b) >= 1.0: # 只有变化明显才画箭头，避免图表杂乱
                ax.annotate('', xy=(x, r), xytext=(x, b),
                            arrowprops=dict(arrowstyle='->', color=c, alpha=0.6, lw=1.5))
                # 标注差值
                ax.text(x + 0.05, (r + b) / 2, f"{r-b:+.0f}", color=c, fontsize=8, va='center', fontweight='bold')
            
        plotted_something = True

    # 设置 X 轴
    ax.set_xticks(range(len(sorted_windows)))
    ax.set_xticklabels(sorted_windows)
    ax.set_xlabel("Observation Window Size (Sensitivity)")
    
    ax.set_ylabel("Value (mmHg / bpm)")
    ax.set_title("多窗口轨迹分析 (Multi-Window Trajectory)\n(Solid: Recent, Dashed: Baseline)")
    
    # 添加说明栏 (解释多窗口轨迹含义)
    explanation = "说明：实线代表近期状态，虚线代表基线状态。\n" \
                  "箭头表示从基线到近期的变化方向和幅度。\n" \
                  "左侧(3pt)窗口小更敏感，反映近期瞬时变化；右侧(30pt)窗口大更平滑，反映长期趋势。"
    plt.figtext(0.5, 0.01, explanation, ha="center", fontsize=9, 
                bbox={"facecolor":"#FFF9C4", "alpha":0.5, "pad":5, "edgecolor":"#E0E0E0"})
    
    # 调整布局以容纳底部说明文字
    plt.subplots_adjust(bottom=0.18)
    
    if plotted_something:
        ax.legend(loc='best', fontsize='small', ncol=2)
    ax.grid(True, linestyle='--', alpha=0.3)

    if output_dir:
        plt.savefig(path, dpi=150)
        plt.close()
        return path
    else:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        plt.close()
        buf.seek(0)
        data = base64.b64encode(buf.read()).decode('utf-8')
        return f"data:image/png;base64,{data}"
