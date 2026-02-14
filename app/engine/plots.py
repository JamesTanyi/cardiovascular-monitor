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
from datetime import datetime


def plot_time_series(records, steady_result, emergency_result, events_by_segment, output_dir=None):
    """
    增强版血压时间序列图：
    - SBP/DBP 折线
    - 稳态段背景色
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
    # 1. 绘制 SBP/DBP 折线
    # ==========================
    ax.plot(times, sbp, label="SBP", color="#E53935", linewidth=2)
    ax.plot(times, dbp, label="DBP", color="#1E88E5", linewidth=2)

    # ==========================
    # 2. 稳态段背景色
    # ==========================
    for seg in steady_result.get("segments", []):
        ax.axvspan(seg["start"], seg["end"], color="#E0E0E0", alpha=0.15)

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
    ax.legend()
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


def plot_baseline_vs_recent(steady_result: Dict, output_dir: str) -> str:
    """生成基线 vs 最近稳态中位数对比条形图"""
    os.makedirs(output_dir, exist_ok=True)

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

    path = os.path.join(output_dir, "baseline_vs_recent.png")
    plt.savefig(path, dpi=150)
    plt.close()
    return path


def plot_trajectory(steady_result: Dict, output_dir: str) -> str:
    """生成多时间尺度轨迹图"""
    os.makedirs(output_dir, exist_ok=True)

    trajectory = steady_result.get("trajectory", {})
    if not trajectory:
        return ""

    plt.figure(figsize=(10, 6))

    for m, steps in trajectory.items():
        xs = [s["window"] for s in steps]
        ys = [s["delta"] for s in steps]
        plt.plot(xs, ys, marker="o", label=m.upper())

    plt.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    plt.xlabel("Window")
    plt.ylabel("Median Delta")
    plt.title("Multi-Window Trajectory")
    plt.legend()
    plt.tight_layout()

    path = os.path.join(output_dir, "trajectory.png")
    plt.savefig(path, dpi=150)
    plt.close()
    return path
