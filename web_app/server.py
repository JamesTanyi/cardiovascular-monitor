import sys
import os
import traceback
import json
import re
import importlib
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

# --- 1. 路径自动补丁 (解决 ModuleNotFoundError) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- 2. 导入外部核心逻辑 ---
from app.ingest.bp_loader import build_single_record_from_payload
from web_app.storage import load_history_for_patient, save_raw_measurement, clear_history_for_patient
from app.engine.temporal_logic import build_temporal_context, evaluate_gap_aware_risk
from app.engine.steady_state import analyze_steady_states # 只导入主函数
from app.engine.risk_level import assess_risk_bundle
from app.engine.language import generate_language_blocks
from app.engine.patterns import analyze_patterns
from app.engine.plots import plot_time_series, plot_bp_scatter, plot_trajectory, plot_volatility_trend

app = Flask(__name__)
CORS(app)

# --- 3. 内置工具函数 (解决函数缺失问题) ---
def _prepare_records_for_analysis(records):
    prepared = []
    for r in records:
        d = r if isinstance(r, dict) else (r.to_dict() if hasattr(r, 'to_dict') else r.__dict__)
        try:
            ts = d.get("timestamp") or d.get("datetime")
            dt_obj = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace(" ", "T"))
            
            sbp = d.get('sbp') or d.get('SBP')
            dbp = d.get('dbp') or d.get('DBP')
            
            if sbp and dbp:
                prepared.append({
                    'datetime': dt_obj,
                    'sbp': float(sbp),
                    'dbp': float(dbp),
                    'pp': float(sbp) - float(dbp),
                    'hr': float(d.get('hr') or 0),
                    # --- 核心修复：保留症状事件 ---
                    'events': d.get('events') or d.get('symptoms') or []
                })
        except: continue
    return prepared

def adapt_steady_for_risk_level(steady_res, records=None):
    """适配器：将稳态分析结果转化为风险评估所需的结构"""
    # 默认值
    base = {"sbp": 120, "dbp": 80, "status": "stable"}
    trend = {"sbp": "stable", "dbp": "stable"}
    
    # 尝试从 5pt (5条记录窗口) 获取最近趋势
    w_recent = steady_res.get("windows", {}).get("5pt", {})
    if w_recent:
        recent = w_recent.get("recent", {}).get("profile", {})
        if recent:
            base["sbp"] = recent.get("sbp", {}).get("median", 120)
            base["dbp"] = recent.get("dbp", {}).get("median", 80)
    elif records:
        # 【修复】数据不足导致无法计算稳态窗口时（冷启动），直接使用最新记录作为基线
        latest = records[-1]
        base["sbp"] = latest.get("sbp", 120)
        base["dbp"] = latest.get("dbp", 80)
        
        # 简单计算瞬时趋势（基于最后两条），用于触发“提醒注意”
        if len(records) >= 2:
            prev = records[-2]
            delta = latest.get("sbp", 0) - prev.get("sbp", 0)
            if delta >= 5: trend["sbp"] = "up"
            elif delta <= -5: trend["sbp"] = "down"
            
    # 从轨迹中提取趋势
    traj = steady_res.get("trajectory", {})
    if traj.get("sbp"):
        trend["sbp"] = traj["sbp"][-1]["status"]
    if traj.get("dbp"):
        trend["dbp"] = traj["dbp"][-1]["status"]
        
    return {"base": base, "trend": trend}

def _generate_hemodynamic_summary(risk_bundle, steady_adapted):
    """生成心血管动力学维度的摘要，强调风险、负荷与趋势"""
    chronic = risk_bundle.get("chronic_tension", 0.0)
    acute = risk_bundle.get("acute_push", 0.0)
    risk_level = risk_bundle.get("acute_risk_level", "low")
    
    # 趋势解读
    trend_map = {"up": "上升 ⬆️", "down": "下降 ⬇️", "stable": "平稳 ➡️"}
    sbp_trend = steady_adapted.get("trend", {}).get("sbp", "stable")
    
    # 动力学状态描述
    load_desc = "正常"
    if chronic > 0.6: load_desc = "高负荷 (High Load)"
    elif chronic > 0.3: load_desc = "中等负荷 (Medium Load)"
    
    plaque_risk = risk_bundle.get("plaque_risk", {})
    plaque_msg = f"- **动脉风险评估**: {plaque_risk.get('level', 'low').upper()} (评分: {plaque_risk.get('score', 0):.2f})"

    return (
        f"## 🩺 动力学核心摘要 (Hemodynamic Core)\n"
        f"- **风险分级**: {risk_level.upper()}\n"
        f"- **血管负荷**: {load_desc} (慢性张力: {chronic:.2f})\n"
        f"{plaque_msg}\n"
        f"- **近期趋势**: {trend_map.get(sbp_trend, '未知')}\n"
        f"- **急性冲击**: {acute:.2f} (反映短期波动强度)"
    )

def _generate_pp_bar_html(pp_value, max_scale=100.0, min_val=None, max_val=None):
    """生成脉压差可视化条形图 HTML"""
    # --- 颜色配置 (Color Configuration) ---
    COLOR_HIGH = "#D32F2F"   # 偏大 (红色)
    COLOR_LOW = "#1976D2"    # 偏小 (蓝色)
    COLOR_NORMAL = "#388E3C" # 正常 (绿色)
    # ------------------------------------

    # 动态调整刻度：取 (100, 历史最大值, 当前值) 的最大者
    final_scale = max(100.0, float(max_scale), float(pp_value))
    
    width_pct = min(100.0, max(5.0, (pp_value / final_scale) * 100.0))
    threshold_60_pos = (60.0 / final_scale) * 100.0
    
    if pp_value >= 60:
        color = COLOR_HIGH
        label = "偏大 (High)"
    elif pp_value <= 20:
        color = COLOR_LOW
        label = "偏小 (Low)"
    else:
        color = COLOR_NORMAL
        label = "正常 (Normal)"

    min_marker = ""
    if min_val is not None:
        min_pos = (float(min_val) / final_scale) * 100.0
        min_pos = max(0.0, min(100.0, min_pos))
        min_marker = f'<div style="position: absolute; left: {min_pos}%; top: -4px; bottom: -4px; width: 2px; background-color: #424242; z-index: 5;" title="历史最低: {int(min_val)}"></div>'

    max_marker = ""
    if max_val is not None:
        max_pos = (float(max_val) / final_scale) * 100.0
        max_pos = max(0.0, min(100.0, max_pos))
        max_marker = f'<div style="position: absolute; left: {max_pos}%; top: -4px; bottom: -4px; width: 2px; background-color: #424242; z-index: 5;" title="历史最高: {int(max_val)}"></div>'
        
    return f"""
<div style="border: 1px solid #eee; padding: 10px; border-radius: 8px; background: #fafafa; margin: 10px 0;">
    <div style="display: flex; justify-content: space-between; font-size: 12px; color: #666; margin-bottom: 5px;">
        <span>脉压差 (PP)</span>
        <span><strong>{int(pp_value)} mmHg</strong> - {label}</span>
    </div>
    <div style="background-color: #e0e0e0; width: 100%; height: 10px; border-radius: 5px; position: relative;">
        <div style="background-color: {color}; width: {width_pct}%; height: 100%; border-radius: 5px; transition: width 0.5s;"></div>
        <div style="position: absolute; left: {threshold_60_pos}%; top: -2px; bottom: -2px; width: 2px; background: rgba(0,0,0,0.1); z-index: 1;" title="60mmHg 警戒线"></div>
        {min_marker}
        {max_marker}
    </div>
    <div style="position: relative; height: 15px; font-size: 10px; color: #999; margin-top: 2px;">
        <span style="position: absolute; left: 0;">0</span>
        <span style="position: absolute; left: {threshold_60_pos}%; transform: translateX(-50%);">60</span>
        <span style="position: absolute; right: 0;">{int(final_scale)}</span>
    </div>
</div>
"""

def _generate_plaque_risk_html(plaque_risk):
    """生成斑块稳定性风险可视化 HTML"""
    score = plaque_risk.get("score", 0.0)
    level = plaque_risk.get("level", "low")
    reasons = plaque_risk.get("reasons", [])
    
    # 颜色配置
    COLOR_HIGH = "#D32F2F"   # High (Red)
    COLOR_MOD = "#FBC02D"    # Moderate (Yellow/Orange)
    COLOR_LOW = "#388E3C"    # Low (Green)
    
    if level == "high":
        color = COLOR_HIGH
        label = "高风险 (High)"
    elif level == "moderate":
        color = COLOR_MOD
        label = "中风险 (Moderate)"
    else:
        color = COLOR_LOW
        label = "低风险 (Low)"
    
    # 宽度百分比 (0-1.0 -> 0-100%)
    width_pct = min(100.0, max(5.0, score * 100.0))
    
    # 翻译原因
    reason_map = {
        "high_pulse_pressure": "脉压差过大",
        "high_bp_variability": "血压波动剧烈",
        "morning_surge": "晨峰现象",
        "tachycardia_stress": "心率过快",
        "high_wall_tension": "血管壁张力高"
    }
    translated_reasons = [reason_map.get(r, r) for r in reasons]
    reason_text = "、".join(translated_reasons) if translated_reasons else "无显著动力学风险因素"

    return f"""
<div style="border: 1px solid #eee; padding: 10px; border-radius: 8px; background: #fafafa; margin: 10px 0;">
    <div style="display: flex; justify-content: space-between; font-size: 12px; color: #666; margin-bottom: 5px;">
        <span><strong>动脉风险评估 (Arterial Risk)</strong></span>
        <span style="color: {color}; font-weight: bold;">{label}</span>
    </div>
    <div style="background-color: #e0e0e0; width: 100%; height: 10px; border-radius: 5px; position: relative; margin-bottom: 8px;">
        <!-- 阈值参考线 -->
        <div style="position: absolute; left: 40%; top: -2px; bottom: -2px; width: 1px; background: #fff; z-index: 1;" title="中风险阈值 (0.4)"></div>
        <div style="position: absolute; left: 70%; top: -2px; bottom: -2px; width: 1px; background: #fff; z-index: 1;" title="高风险阈值 (0.7)"></div>
        <div style="background-color: {color}; width: {width_pct}%; height: 100%; border-radius: 5px; transition: width 0.5s;"></div>
    </div>
    <div style="font-size: 11px; color: #555; display: flex; align-items: center;">
        <span style="color: #999; margin-right: 5px;">风险因素:</span> 
        <span>{reason_text}</span>
    </div>
</div>
"""

# --- 4. 完整的 12 步 Pipeline ---

def run_pipeline_for_patient(patient_id: str, new_payload: dict):
    log_prefix = f"[{patient_id}]"
    try:
        print(f"\n--- {log_prefix} 开始分析 ---")
        # 1-4 步：数据准备
        print(f"{log_prefix} 步骤 1: 构建当前记录...")
        current_rec = build_single_record_from_payload(new_payload)
        print(f"{log_prefix} 步骤 2: 加载历史数据...")
        history = load_history_for_patient(patient_id)
        print(f"{log_prefix} 步骤 3: 合并记录 (历史 {len(history)} 条 + 当前 1 条)...")
        all_records = history + [current_rec]
        print(f"{log_prefix} 步骤 4: 数据标准化...")
        normalized = [r.to_dict() for r in all_records]

        # 5-6 步：时间逻辑
        print(f"{log_prefix} 步骤 5: 构建时间上下文...")
        tc = build_temporal_context(normalized)
        print(f"{log_prefix} 步骤 6: 评估测量间隔风险...")
        gap_risk = evaluate_gap_aware_risk(tc)

        # 7 步：预处理
        print(f"{log_prefix} 步骤 7: 准备稳态分析输入...")
        steady_input = _prepare_records_for_analysis(normalized)
        print(f"{log_prefix} 调试: 稳态分析输入长度: {len(steady_input)}")

        # 计算历史最大脉压差 (用于图表缩放)
        max_pp_history = 0.0
        min_pp_history = None
        if steady_input:
            pp_values = [r['pp'] for r in steady_input]
            max_pp_history = max(pp_values)
            min_pp_history = min(pp_values)

        if not steady_input:
            return {"user": "数据收集不足，暂无趋势分析。"}

        # 8-11 步：核心稳态分析
        print(f"{log_prefix} 步骤 8: 执行稳态分析...")
        steady_result = analyze_steady_states(steady_input)
        
        # 【调整】提前执行模式识别，以便风险评估模块使用其结果（如波动性、晨峰）
        patterns = analyze_patterns(steady_input)

        print(f"{log_prefix} 步骤 9-10: 风险评估...")
        steady_adapted = adapt_steady_for_risk_level(steady_result, steady_input)
        steady_for_risk = {
            "windows": steady_result.get("windows", {}),
            "base": steady_adapted["base"],
            "trend": steady_adapted["trend"]
        }
        risk_bundle = assess_risk_bundle(steady_input, steady_for_risk, steady_result.get("events_by_segment", []), patterns=patterns)
        
        # 【修复】将步骤 6 计算的间隔风险注入 risk_bundle，使其能被报告模块使用
        risk_bundle["gap_risk"] = gap_risk
        
        # 12 步：文案生成
    
        print(f"{log_prefix} 步骤 12: 生成分析报告...")
        
        # --- 补充：生成可视化图表 ---
        # 改用 Base64 内存生成，兼容 GAE 只读文件系统 (output_dir=None)
        # 构造一个临时的 emergency_result 结构供绘图使用
        is_emergency = risk_bundle.get("acute_risk_level") in ["high", "critical"]
        emergency_dummy = {"emergency": is_emergency}
        
        # 生成 Base64 图片字符串
        # 注意：这里不再创建目录，也不再保存文件
        ts_url = plot_time_series(steady_input, steady_result, emergency_dummy, steady_result.get("events_by_segment", []), output_dir=None)
        scatter_url = plot_bp_scatter(steady_input, output_dir=None)
        trajectory_url = plot_trajectory(steady_result, output_dir=None)
        volatility_url = plot_volatility_trend(steady_result, output_dir=None)
        
        # --- 核心改动：先提取判定结果，防止后续因报错而丢失 ---
        final_risk = risk_bundle.get("acute_risk_level", "low")

        try:
            # 将 patterns 放入 figure_paths 传给 language 模块（复用现有参数结构）
            figure_paths = {
                "patterns": patterns,
                "time_series_url": ts_url,
                "scatter_url": scatter_url,
                "trajectory_url": trajectory_url,
                "volatility_url": volatility_url
            }
            language_res = generate_language_blocks(steady_input, steady_result, risk_bundle, figure_paths=figure_paths)
            
            # --- 注入动力学摘要 (置于报告最前) ---
            hemo_summary = _generate_hemodynamic_summary(risk_bundle, steady_adapted)
            
            # --- 注入脉压差可视化 ---
            pp_val = steady_adapted["base"]["sbp"] - steady_adapted["base"]["dbp"]
            pp_bar = _generate_pp_bar_html(pp_val, max_scale=max_pp_history, min_val=min_pp_history, max_val=max_pp_history)
            
            # --- 注入斑块风险可视化 ---
            plaque_risk = risk_bundle.get("plaque_risk", {})
            plaque_bar = _generate_plaque_risk_html(plaque_risk)
            
            language_res["doctor"] = hemo_summary + "\n" + pp_bar + "\n" + plaque_bar + "\n" + language_res.get("doctor", "")
            # 用户版也增加简单提示
            language_res["user"] = f"【健康提示】当前风险等级: {final_risk.upper()} | 趋势: {steady_adapted.get('trend', {}).get('sbp', 'stable')}\n\n" + language_res.get("user", "")
            
            # 辅助函数：隐藏日志中的 Base64 图片数据，防止刷屏
            def _clean_log(text):
                if not text: return ""
                return re.sub(r'data:image/[^"]+base64,[^"]+', '[BASE64_IMAGE_DATA_HIDDEN]', text)

            print(f"\n{log_prefix} " + "="*40)
            print(f"{log_prefix} 【用户版报告】\n" + language_res.get("user", ""))
            print(f"{log_prefix} " + "-" * 20)
            print(f"{log_prefix} 【家属版报告】\n" + language_res.get("family", ""))
            print(f"{log_prefix} " + "-" * 20)
            print(f"{log_prefix} 【医生版报告】\n" + _clean_log(language_res.get("doctor", "")))
            print(f"{log_prefix} " + "="*40 + "\n")
        except Exception as lang_e:
            print(f"!!! {log_prefix} 文案生成局部失败 (language.py 问题): {lang_e}")
            # 如果文案崩了，构造一个基础的返回包
            language_res = {
                "user": "监测到指标波动，请注意休息。",
                "family": "长辈血压有变化，建议查阅详情。",
                "doctor": f"诊断逻辑运行成功，但报告模块异常: {str(lang_e)}"
            }

        # --- 确保测试脚本 100% 能读到判定结果 ---
        language_res["acute_risk_level"] = final_risk 
        language_res["total_score"] = risk_bundle.get("total_score", 0)
        # 【修复】将核心评分透传给前端/测试脚本，解决测试脚本读不到慢性评分的问题
        language_res["chronic_tension"] = risk_bundle.get("chronic_tension", 0.0)
        language_res["acute_push"] = risk_bundle.get("acute_push", 0.0)

        print(f">>> {log_prefix} [成功] 分析完成，判定等级: {final_risk}")
        return language_res

    except Exception as e:
        # 这是你原有的最外层异常捕获
        print(f"!!! {log_prefix} 流程错误: {str(e)}")
        traceback.print_exc()
        # 即使这里崩了，也尝试把能拿到的风险等级带回去，防止测试显示 unknown
        return {
            "user": "分析系统异常，请稍后再试。",
            "acute_risk_level": locals().get('final_risk', "unknown")
        }

# --- 5. 路由 ---

@app.route("/", methods=["GET"])
def index():
    pid = request.args.get("pid", "test_user")
    history = load_history_for_patient(pid)
    records_to_show = [r.to_dict() for r in history][-10:]
    return render_template("index.html", records=records_to_show, assigned_pid=pid)

@app.route("/api/v1/measurements", methods=["POST"])
def receive_measurement():
    data = request.get_json() if request.is_json else request.form.to_dict()
    pid = data.get("patient_id", "test_user")
    save_raw_measurement(data)
    result = run_pipeline_for_patient(pid, data)

    if request.is_json:
        return jsonify({"status": "ok", "analysis": result})
    
    # 如果是表单提交，重新渲染页面并带上分析结果
    history = load_history_for_patient(pid)
    records_to_show = [r.to_dict() for r in history][-10:]
    return render_template("index.html", records=records_to_show, assigned_pid=pid, analysis=result)

@app.route("/api/v1/history", methods=["DELETE"])
def reset_history():
    pid = request.args.get("patient_id", "test_user")
    clear_history_for_patient(pid)
    return jsonify({"status": "ok", "message": f"History for {pid} cleared."})

@app.route("/test-dashboard")
def test_dashboard():
    """渲染测试结果仪表盘页面"""
    results_path = os.path.join(project_root, 'data', 'test_results.json')
    test_results = []
    try:
        with open(results_path, 'r', encoding='utf-8') as f:
            test_results = json.load(f)
    except FileNotFoundError:
        print("未找到测试结果文件: test_results.json")
    except json.JSONDecodeError:
        print("解析 test_results.json 文件失败")
    return render_template("test_dashboard.html", test_results=test_results)

@app.route("/api/rerun-tests", methods=["POST"])
def rerun_tests():
    """API: 触发后端重新运行测试套件"""
    try:
        # 动态导入位于根目录的 run_test_suite 模块
        import run_test_suite
        importlib.reload(run_test_suite) # 确保加载最新代码
        
        print(">>> 正在重新运行测试套件 (run_test_suite.py)...")
        run_test_suite.run_suite()
        
        return jsonify({"status": "ok", "message": "测试已完成，数据已更新"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/sw.js')
def service_worker():
    """服务 Service Worker 文件，使其作用域为根目录"""
    return send_from_directory(os.path.join(app.root_path, 'static'), 'sw.js')

if __name__ == "__main__":
    # --- 云服务器适配 ---
    # 1. 获取端口：云平台通常通过环境变量 PORT 传递端口，如果本地运行则默认 5000
    port = int(os.environ.get("PORT", 5000))
    # 2. 调试模式：生产环境通常通过设置 FLASK_DEBUG=false 来关闭
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    
    print(f"启动服务器: Host=0.0.0.0, Port={port}, Debug={debug}")
    app.run(host="0.0.0.0", port=port, debug=debug)