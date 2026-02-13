import sys
import os
import traceback
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template
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
from app.engine.plots import plot_time_series, plot_bp_scatter

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
    
    # 尝试从 14w (14条记录窗口) 获取最近趋势
    w14 = steady_res.get("windows", {}).get("14w", {})
    if w14:
        recent = w14.get("recent", {}).get("profile", {})
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

        if not steady_input:
            return {"user": "数据收集不足，暂无趋势分析。"}

        # 8-11 步：核心稳态分析
        print(f"{log_prefix} 步骤 8: 执行稳态分析...")
        steady_result = analyze_steady_states(steady_input)
        
        print(f"{log_prefix} 步骤 9-10: 风险评估...")
        steady_adapted = adapt_steady_for_risk_level(steady_result, steady_input)
        steady_for_risk = {
            "windows": steady_result.get("windows", {}),
            "base": steady_adapted["base"],
            "trend": steady_adapted["trend"]
        }
        risk_bundle = assess_risk_bundle(steady_input, steady_for_risk, steady_result.get("events_by_segment", []))
        
        # 【修复】将步骤 6 计算的间隔风险注入 risk_bundle，使其能被报告模块使用
        risk_bundle["gap_risk"] = gap_risk
        
        # 12 步：文案生成
    
        print(f"{log_prefix} 步骤 12: 生成分析报告...")
        
        # 补充：模式识别
        patterns = analyze_patterns(steady_input)
        
        # --- 补充：生成可视化图表 ---
        # 1. 准备目录: web_app/static/charts/{patient_id}
        static_dir = os.path.join(project_root, "web_app", "static")
        charts_sub_dir = os.path.join("charts", patient_id)
        output_dir = os.path.join(static_dir, charts_sub_dir)
        os.makedirs(output_dir, exist_ok=True)

        # 2. 生成图表
        # 构造一个临时的 emergency_result 结构供绘图使用
        is_emergency = risk_bundle.get("acute_risk_level") in ["high", "critical"]
        emergency_dummy = {"emergency": is_emergency}
        
        # 生成文件名带时间戳防止缓存 (可选，这里简化处理直接覆盖)
        plot_time_series(steady_input, steady_result, emergency_dummy, steady_result.get("events_by_segment", []), output_dir)
        plot_bp_scatter(steady_input, output_dir)

        # 3. 构造 URL 路径 (供前端/Markdown 使用)
        ts_url = f"/static/{charts_sub_dir}/time_series_marked.png?t={datetime.now().timestamp()}"
        scatter_url = f"/static/{charts_sub_dir}/bp_scatter.png?t={datetime.now().timestamp()}"
        
        # --- 核心改动：先提取判定结果，防止后续因报错而丢失 ---
        final_risk = risk_bundle.get("acute_risk_level", "low")

        try:
            # 将 patterns 放入 figure_paths 传给 language 模块（复用现有参数结构）
            figure_paths = {
                "patterns": patterns,
                "time_series_url": ts_url,
                "scatter_url": scatter_url
            }
            language_res = generate_language_blocks(steady_input, steady_result, risk_bundle, figure_paths=figure_paths)
            
            print(f"\n{log_prefix} " + "="*40)
            print(f"{log_prefix} 【用户版报告】\n" + language_res.get("user", ""))
            print(f"{log_prefix} " + "-" * 20)
            print(f"{log_prefix} 【家属版报告】\n" + language_res.get("family", ""))
            print(f"{log_prefix} " + "-" * 20)
            print(f"{log_prefix} 【医生版报告】\n" + language_res.get("doctor", ""))
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)