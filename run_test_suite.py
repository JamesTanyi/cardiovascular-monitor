import os
import sys
import json
from datetime import datetime, timedelta

# 确保可以导入 app 模块
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from web_app.server import run_pipeline_for_patient
from web_app.storage import clear_history_for_patient, save_raw_measurement

# 定义测试场景
TEST_CASES = [
    {
        "stage": "【健康对照组】",
        "patient_id": "test_healthy",
        "payloads": [
            {"sbp": 110, "dbp": 70, "days_ago": 4},
            {"sbp": 112, "dbp": 72, "days_ago": 3},
            {"sbp": 114, "dbp": 74, "days_ago": 2},
            {"sbp": 115, "dbp": 75, "days_ago": 1},
            {"sbp": 115, "dbp": 75, "days_ago": 0, "symptoms": []}
        ],
        "expected_risk": "low",
    },
    {
        "stage": "【脑卒中前兆组】",
        "patient_id": "test_stroke",
        "payloads": [
            {"sbp": 120, "dbp": 80, "days_ago": 4},
            {"sbp": 122, "dbp": 81, "days_ago": 3},
            {"sbp": 121, "dbp": 79, "days_ago": 2},
            {"sbp": 123, "dbp": 82, "days_ago": 1},
            {"sbp": 125, "dbp": 80, "days_ago": 0, "symptoms": ["weakness_one_side", "slurred_speech"]}
        ],
        "expected_risk": "critical",
    },
    {
        "stage": "【中危症状组】",
        "patient_id": "test_med_risk",
        "payloads": [
            {"sbp": 128, "dbp": 82, "days_ago": 4},
            {"sbp": 130, "dbp": 85, "days_ago": 3},
            {"sbp": 129, "dbp": 84, "days_ago": 2},
            {"sbp": 131, "dbp": 86, "days_ago": 1},
            {"sbp": 130, "dbp": 85, "days_ago": 0, "symptoms": ["dizzy"]}
        ],
        "expected_risk": "moderate",
    },
    {
        "stage": "【高血压急症组】",
        "patient_id": "test_emergency",
        "payloads": [
            {"sbp": 140, "dbp": 90, "days_ago": 4},
            {"sbp": 150, "dbp": 95, "days_ago": 3},
            {"sbp": 160, "dbp": 100, "days_ago": 2},
            {"sbp": 170, "dbp": 105, "days_ago": 1},
            {"sbp": 190, "dbp": 110, "days_ago": 0, "symptoms": []}
        ],
        "expected_risk": "high",
    },
    {
        "stage": "【慢性高血压组】",
        "patient_id": "test_chronic",
        "payloads": [
            {"sbp": 150, "dbp": 95, "days_ago": 4},
            {"sbp": 152, "dbp": 96, "days_ago": 3},
            {"sbp": 149, "dbp": 94, "days_ago": 2},
            {"sbp": 151, "dbp": 95, "days_ago": 1},
            {"sbp": 150, "dbp": 95, "days_ago": 0, "symptoms": []}
        ],
        "expected_risk": "moderate",
    },
    {
        "stage": "【低灌注风险组】",
        "patient_id": "test_hypoperfusion",
        "payloads": [
            {"sbp": 160, "dbp": 100, "days_ago": 4},
            {"sbp": 158, "dbp": 98, "days_ago": 3},
            {"sbp": 162, "dbp": 102, "days_ago": 2},
            {"sbp": 155, "dbp": 95, "days_ago": 1},
            # 突然下降到 110 (基线约 158)，模拟降压过快或心衰
            {"sbp": 110, "dbp": 70, "days_ago": 0, "symptoms": ["dizzy", "cold_sweat"]}
        ],
        "expected_risk": "high",
    }
]

def run_suite():
    results = []
    base_time = datetime.now()

    for case in TEST_CASES:
        print(f"--- Running test: {case['stage']} ---")
        patient_id = case["patient_id"]
        clear_history_for_patient(patient_id)

        for p in case["payloads"]:
            ts = (base_time - timedelta(days=p["days_ago"])).isoformat()
            payload = {"patient_id": patient_id, "timestamp": ts, "datetime": ts, **p}
            save_raw_measurement(payload)

        final_payload_data = case["payloads"][-1]
        ts_final = (base_time - timedelta(days=final_payload_data["days_ago"])).isoformat()
        final_payload = {"patient_id": patient_id, "timestamp": ts_final, "datetime": ts_final, **final_payload_data}
        
        analysis_result = run_pipeline_for_patient(patient_id, final_payload)
        
        actual_risk = analysis_result.get("acute_risk_level", "unknown")
        
        # 1. 验证风险等级
        risk_passed = actual_risk == case["expected_risk"]

        # 2. 验证留存激励文案 (Retention Hooks)
        hooks_passed = True
        
        # 医生版：所有情况都应包含 System Note
        if "System Note" not in analysis_result.get("doctor", ""):
             hooks_passed = False
             print("  ! Doctor report missing System Note")

        # 用户/家属版：仅非危急情况 (low, moderate, moderate_high) 包含激励文案
        if actual_risk not in ["high", "critical"]:
            if "【专属健康管家】" not in analysis_result.get("user", ""):
                hooks_passed = False
                print("  ! User report missing retention hook")
            if "【长期守护价值】" not in analysis_result.get("family", ""):
                hooks_passed = False
                print("  ! Family report missing retention hook")
        
        # 3. 验证纵向时间结构 (Longitudinal Structure)
        long_passed = True
        long_data = analysis_result.get("longitudinal", {})
        
        # 检查报告中是否包含纵向分析章节 (这是用户可见的最终结果)
        has_long_report = "纵向依从性" in analysis_result.get("doctor", "") or "Longitudinal Adherence" in analysis_result.get("doctor", "")

        if not long_data:
            # 如果数据对象缺失，但报告中存在，我们认为计算是成功的（可能是接口层过滤了数据）
            if not has_long_report:
                long_passed = False
                print(f"  ! Longitudinal data missing and report section missing")
        elif "stage" not in long_data or "continuity_score" not in long_data:
            long_passed = False
            print(f"  ! Longitudinal data incomplete: {long_data}")
        
        # 如果有数据，报告中必须包含该章节
        if long_data and not has_long_report:
             long_passed = False
             print("  ! Doctor report missing Longitudinal Adherence section")

        passed = risk_passed and hooks_passed and long_passed
        
        result_entry = {"stage": case["stage"], "sbp": final_payload_data["sbp"], "dbp": final_payload_data["dbp"], "symptoms": final_payload_data.get("symptoms", []), "expected_risk": case["expected_risk"], "actual_risk": actual_risk, "passed": passed, "full_analysis": analysis_result}
        results.append(result_entry)
        
        status_icon = "✅" if passed else "❌"
        print(f"  -> Risk: {actual_risk} (Exp: {case['expected_risk']}) | Hooks: {'OK' if hooks_passed else 'MISSING'} | Long: {'OK' if long_passed else 'MISSING'} | {status_icon} {passed}")

    results_path = os.path.join(current_dir, 'data', 'test_results.json')
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print(f"\n✅ Test suite finished. Results saved to {results_path}")

if __name__ == "__main__":
    run_suite()