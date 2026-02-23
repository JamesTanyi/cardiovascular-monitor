import unittest
import sys
import os
from datetime import datetime, timedelta

# 确保可以导入 app 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.engine.risk_level import assess_risk_bundle

class TestRiskLevel(unittest.TestCase):
    def setUp(self):
        """准备通用的测试数据结构"""
        self.base_time = datetime(2023, 1, 1, 12, 0)
        
        # 一个非常正常、稳定的记录
        self.normal_records = [{
            'datetime': self.base_time,
            'sbp': 120, 'dbp': 80, 'pp': 40, 'hr': 70, 'events': []
        }]
        
        # 一个用于风险评估的正常稳态结构
        self.normal_steady_for_risk = {
            "base": {"sbp": 120, "dbp": 80},
            "trend": {"sbp": "stable", "dbp": "stable"}
        }

    def test_low_risk_scenario(self):
        """测试：所有指标正常，无症状，应判定为低风险"""
        risk_bundle = assess_risk_bundle(
            self.normal_records, 
            self.normal_steady_for_risk, 
            []
        )
        self.assertEqual(risk_bundle['acute_risk_level'], 'low', "正常情况应为 low risk")
        self.assertLess(risk_bundle['chronic_tension'], 0.3, "正常情况慢性张力应很低")
        self.assertLess(risk_bundle['acute_push'], 0.3, "正常情况急性推力应很低")

    def test_high_chronic_deviation(self):
        """测试偏离程度（慢性）：长期高血压（基线高），应有高的慢性张力"""
        high_base_records = [
            {'datetime': self.base_time - timedelta(days=i), 'sbp': 150, 'dbp': 95, 'pp': 55, 'hr': 80, 'events': []}
            for i in range(5)
        ]
        high_steady_for_risk = {
            "base": {"sbp": 150, "dbp": 95},
            "trend": {"sbp": "stable", "dbp": "stable"}
        }
        risk_bundle = assess_risk_bundle(high_base_records, high_steady_for_risk, [])
        
        self.assertGreater(risk_bundle['chronic_tension'], 0.5, "长期高血压，慢性张力应较高")
        # 即使基线高，但如果近期稳定，急性风险可能只是中等
        self.assertIn(risk_bundle['acute_risk_level'], ['moderate', 'moderate_high'])

    def test_high_acute_deviation_and_reversal(self):
        """测试偏离程度（急性）与反转：基线正常，但近期急剧升高，应有高急性推力"""
        records = [
            {'datetime': self.base_time - timedelta(days=1), 'sbp': 120, 'dbp': 80, 'pp': 40, 'hr': 70, 'events': []},
            {'datetime': self.base_time, 'sbp': 165, 'dbp': 100, 'pp': 65, 'hr': 90, 'events': []}
        ]
        # 趋势为 "up"，构成反转
        up_trend_steady = {
            "base": {"sbp": 125, "dbp": 80}, # 基线正常
            "trend": {"sbp": "up", "dbp": "up"}
        }
        risk_bundle = assess_risk_bundle(records, up_trend_steady, [])
        
        self.assertGreater(risk_bundle['acute_push'], 0.5, "近期急剧升高，急性推力应较高")
        self.assertIn(risk_bundle['acute_risk_level'], ['moderate_high', 'high'], "急剧升高，风险等级应偏高")

    def test_emergency_symptom_triggers_critical_risk(self):
        """测试紧急情况（症状）：出现高危症状（如胸痛），即使血压正常，也应直接判定为高危"""
        # 即使血压完全正常
        records = self.normal_records
        steady_for_risk = self.normal_steady_for_risk
        # 但出现了高危症状
        events = [['chest_pain']] 
        
        risk_bundle = assess_risk_bundle(records, steady_for_risk, events)
        
        self.assertIn(risk_bundle['acute_risk_level'], ['high', 'critical'], "高危症状应触发高风险等级")
        self.assertEqual(risk_bundle['symptom_level'], 'high', "症状等级应被识别为 high")

    def test_emergency_combination(self):
        """测试紧急情况（组合）：高偏离度（高血压值）+ 高危症状，应判定为危急"""
        records = [
            {'datetime': self.base_time, 'sbp': 185, 'dbp': 115, 'pp': 70, 'hr': 100, 'events': ['chest_pain', 'dizzy']}
        ]
        # 此时的基线和趋势都非常差
        critical_steady = {
            "base": {"sbp": 185, "dbp": 115},
            "trend": {"sbp": "up", "dbp": "up"}
        }
        events = [['chest_pain', 'dizzy']]
        
        risk_bundle = assess_risk_bundle(records, critical_steady, events)
        
        self.assertEqual(risk_bundle['acute_risk_level'], 'critical', "高血压+高危症状，应为 critical")
        self.assertGreater(risk_bundle['total_score'], 100, "危急情况总分应很高")

    def test_no_data_input(self):
        """测试：无输入数据时的处理，应返回安全的默认低风险"""
        risk_bundle = assess_risk_bundle([], {}, [])
        self.assertEqual(risk_bundle['acute_risk_level'], 'low')
        self.assertEqual(risk_bundle['total_score'], 0)

    def test_plaque_risk_calculation(self):
        """测试斑块稳定性风险计算 (Plaque Risk)"""
        # 构造一个高风险场景
        # SBP=165 (>160) -> +0.2 (High Wall Tension)
        # PP=75 (>60) -> +0.4 (High Pulse Pressure)
        # HR=95 (>90) -> +0.1 (Tachycardia)
        records = [
            {'datetime': self.base_time, 'sbp': 165, 'dbp': 90, 'pp': 75, 'hr': 95, 'events': []}
        ]
        steady_data = {
            "base": {"sbp": 165, "dbp": 90},
            "trend": {"sbp": "stable", "dbp": "stable"}
        }
        
        # 模拟模式识别结果 (传入 patterns 参数)
        # Variability=high -> +0.3
        # Morning Surge=present -> +0.2
        patterns = {
            "variability": "high",
            "morning_surge": "present"
        }
        
        # 总分预期: 0.2 + 0.4 + 0.1 + 0.3 + 0.2 = 1.2 -> 归一化上限为 1.0
        
        risk_bundle = assess_risk_bundle(records, steady_data, [], patterns=patterns)
        
        plaque_risk = risk_bundle.get("plaque_risk", {})
        
        self.assertAlmostEqual(plaque_risk.get('score'), 1.0)
        self.assertEqual(plaque_risk.get('level'), 'high')
        self.assertIn("high_pulse_pressure", plaque_risk.get('reasons', []))
        self.assertIn("morning_surge", plaque_risk.get('reasons', []))

    def test_widened_pulse_pressure_risk(self):
        """测试：单纯脉压差过大 (>60mmHg) 应将风险提升至 moderate"""
        # SBP 135, DBP 65 -> PP 70
        # 绝对值未超标 (170/105)，基线假设正常，但 PP 很大
        records = [{
            'datetime': self.base_time,
            'sbp': 135, 'dbp': 65, 'pp': 70, 'hr': 70, 'events': []
        }]
        steady_data = {
            "base": {"sbp": 135, "dbp": 65},
            "trend": {"sbp": "stable", "dbp": "stable"}
        }
        
        risk_bundle = assess_risk_bundle(records, steady_data, [])
        
        self.assertEqual(risk_bundle['acute_risk_level'], 'moderate', "脉压差过大应触发中等风险")
        self.assertIn('widened_pulse_pressure', risk_bundle['assessment_reasons'])

    def test_plaque_risk_moderate(self):
        """测试：中等斑块风险 (仅脉压差大，无其他叠加因素)"""
        # PP=65 -> score += 0.4 -> level moderate (>=0.4)
        records = [{
            'datetime': self.base_time,
            'sbp': 125, 'dbp': 60, 'pp': 65, 'hr': 70, 'events': []
        }]
        steady_data = {"base": {"sbp": 125, "dbp": 60}, "trend": {"sbp": "stable", "dbp": "stable"}}
        
        risk_bundle = assess_risk_bundle(records, steady_data, [])
        plaque = risk_bundle.get("plaque_risk", {})
        
        self.assertEqual(plaque.get('level'), 'moderate')
        self.assertIn('high_pulse_pressure', plaque.get('reasons', []))

if __name__ == '__main__':
    unittest.main(verbosity=2)