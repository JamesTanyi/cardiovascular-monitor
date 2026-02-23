import unittest
import sys
import os
from datetime import datetime, timedelta

# 确保可以导入 app 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.engine.plots import plot_time_series, plot_volatility_trend
from app.engine.language import _generate_doctor_text, generate_language_blocks
from web_app.server import _generate_plaque_risk_html

class TestVisualsAndReport(unittest.TestCase):
    def setUp(self):
        self.base_time = datetime(2023, 1, 1, 12, 0)
        # 构造 20 条模拟数据
        self.records = [
            {'datetime': self.base_time + timedelta(hours=i), 'sbp': 120+i%10, 'dbp': 80+i%5, 'pp': 40, 'hr': 70}
            for i in range(20)
        ]
        # 模拟稳态分析结果 (包含两个分段，用于测试趋势线连接)
        self.steady_result = {
            "segments": [
                {
                    "start": self.base_time,
                    "end": self.base_time + timedelta(hours=10),
                    "stability": 0.8,
                    "count": 10,
                    "type": "platform",
                    "profile": {
                        "sbp": {"median": 125, "iqr": 5, "q1": 122, "q3": 127},
                        "dbp": {"median": 82, "iqr": 3, "q1": 80, "q3": 83},
                        "pp": {"median": 43, "iqr": 4, "q1": 41, "q3": 45}
                    }
                },
                {
                    "start": self.base_time + timedelta(hours=10),
                    "end": self.base_time + timedelta(hours=20),
                    "stability": 0.7,
                    "count": 10,
                    "type": "change",
                    "profile": {
                        "sbp": {"median": 130, "iqr": 8, "q1": 126, "q3": 134},
                        "dbp": {"median": 85, "iqr": 4, "q1": 83, "q3": 87},
                        "pp": {"median": 45, "iqr": 6, "q1": 42, "q3": 48}
                    }
                }
            ],
            "windows": {}
        }
        self.emergency_result = {"emergency": False}
        self.events = []
        self.risk_bundle = {
            "chronic_tension": 0.2,
            "acute_push": 0.1,
            "symptom_level": "none",
            "acute_risk_level": "low",
            "plaque_risk": {"level": "moderate", "score": 0.5, "reasons": ["high_bp_variability"]},
            "longitudinal": {
                "stage": "baseline",
                "ux_phase": "P2_BASELINE", # Mocking Phase 2
                "days_active": 5,
                "continuity_score": 1.0,
                "cycle_info": {"current_cycle": 1, "day_in_cycle": 5, "is_complete": False},
                "maturity_level": "L1"
            }
        }
        self.figure_paths = {
            "scatter_url": "data:image/png;base64,dummy_scatter",
            "time_series_url": "data:image/png;base64,dummy_ts",
            "trajectory_url": "data:image/png;base64,dummy_trajectory",
            "volatility_url": "data:image/png;base64,dummy_volatility",
            "patterns": {}
        }

    def test_plot_time_series_generation(self):
        """测试：时间序列图生成 (含夜间/晨峰背景、稳态趋势线、置信区间)"""
        print("\n[Test] Generating Time Series Plot...")
        try:
            # 只要不报错且返回 Base64 字符串，即视为绘图逻辑通过
            result = plot_time_series(self.records, self.steady_result, self.emergency_result, self.events, output_dir=None)
            print(f"  -> Success. Image data length: {len(result)} chars")
            self.assertTrue(result.startswith("data:image/png;base64"), "应返回 Base64 图片字符串")
        except Exception as e:
            self.fail(f"plot_time_series 运行失败: {e}")

    def test_plot_volatility_trend_generation(self):
        """测试：波动性趋势图生成"""
        print("\n[Test] Generating Volatility Trend Plot...")
        try:
            result = plot_volatility_trend(self.steady_result, output_dir=None)
            print(f"  -> Success. Image data length: {len(result)} chars")
            self.assertTrue(result.startswith("data:image/png;base64"), "应返回 Base64 图片字符串")
        except Exception as e:
            self.fail(f"plot_volatility_trend 运行失败: {e}")

    def test_doctor_report_content(self):
        """测试：医生版报告内容 (验证新增章节与精简策略)"""
        print("\n[Test] Verifying Doctor Report Content...")
        text = _generate_doctor_text(self.records, self.steady_result, self.risk_bundle, self.figure_paths)
        
        # 1. 验证包含“血压波动性趋势”章节
        self.assertIn("## 4. 血压波动性趋势", text)
        self.assertIn("Volatility Trend", text)
        self.assertIn("展示血压波动范围", text) # 验证图表描述
        
        # 验证包含“脉压差分析”章节
        self.assertIn("## 脉压差分析", text)
        self.assertIn("Pulse Pressure", text)
        
        # 2. 验证包含“动脉风险评估”章节
        self.assertIn("## 动脉风险评估", text)
        self.assertIn("MODERATE", text) # 风险等级
        
        # 3. 验证已移除“临床解读与建议” (医生版不需要过多解释)
        self.assertNotIn("临床解读与建议", text)
        self.assertNotIn("建议考虑24h-ABPM", text) # 具体的建议文本应被移除
        
        # 4. 验证纵向分析章节
        self.assertIn("## 纵向依从性", text)
        self.assertIn("User Stage", text)
        self.assertIn("baseline", text)
        print("  -> Report content verification passed.")

    def test_all_roles_content(self):
        """测试：三角色提示内容 (User, Family, Doctor)"""
        print("\n[Test] Verifying All Roles Content...")
        blocks = generate_language_blocks(self.records, self.steady_result, self.risk_bundle, self.figure_paths)
        
        # 1. User Report
        user_text = blocks["user"]
        # 验证留存激励
        self.assertIn("【专属健康管家】", user_text)
        # 验证 Phase 2 (Baseline) 特定文案 (状态机逻辑)
        self.assertIn("稳态区间正在确认中", user_text)

    def test_cycle_completion_trigger(self):
        """测试：周期完成触发器"""
        # Modify risk_bundle to simulate cycle completion
        self.risk_bundle["longitudinal"]["cycle_info"]["is_complete"] = True
        
        blocks = generate_language_blocks(self.records, self.steady_result, self.risk_bundle, self.figure_paths)
        user_text = blocks["user"]
        
        self.assertIn("🎉 恭喜！您已完成第 1 个监测周期", user_text)
        print("  -> Cycle completion trigger verification passed.")

    def test_family_report_longitudinal_update(self):
        """测试：家属版报告纵向数据更新（责任绑定）"""
        # Modify risk_bundle to simulate low continuity
        self.risk_bundle["longitudinal"]["continuity_score"] = 0.5
        self.risk_bundle["longitudinal"]["days_active"] = 10
        self.risk_bundle["longitudinal"]["cycle_info"]["day_in_cycle"] = 3
        
        blocks = generate_language_blocks(self.records, self.steady_result, self.risk_bundle, self.figure_paths)
        family_text = blocks["family"]
        
        self.assertIn("【档案累计 10 天】", family_text)
        self.assertIn("当前为本周期第 3 天", family_text)
        self.assertIn("近期监测间隔偏长", family_text)
        print("  -> Family report longitudinal update verification passed.")

    def test_plaque_risk_html(self):
        """测试：斑块风险 HTML 可视化组件"""
        print("\n[Test] Verifying Plaque Risk HTML...")
        plaque_risk = {"level": "high", "score": 0.8, "reasons": ["morning_surge"]}
        html = _generate_plaque_risk_html(plaque_risk)
        self.assertIn("width: 80.0%", html) # score 0.8 -> 80%
        self.assertIn("晨峰现象", html)
        print("  -> Plaque risk HTML verification passed.")

if __name__ == '__main__':
    unittest.main(verbosity=2)
