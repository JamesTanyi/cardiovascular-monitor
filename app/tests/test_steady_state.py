import unittest
import sys
import os
from datetime import datetime, timedelta

# 确保可以导入 app 模块 (tests 目录在 app/tests 下，需回溯两级到项目根目录)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.engine.steady_state import (
    analyze_steady_states,
    _compute_profile,
    _compute_stability,
    _slide_windows,
    _segment_states,
    _estimate_user_variability
)

class TestSteadyState(unittest.TestCase):
    def setUp(self):
        """准备测试数据"""
        self.base_time = datetime(2023, 1, 1, 12, 0)
        self.records = []
        
        # 1. 创建前10条稳定的记录 (SBP ~120)
        for i in range(10):
            self.records.append({
                "datetime": self.base_time + timedelta(days=i),
                "sbp": 120 + (i % 2), # 120, 121, 120...
                "dbp": 80 + (i % 2),
                "pp": 40,
                "hr": 70,
                "symptoms": []
            })
        
        # 2. 创建后10条突变的记录 (SBP ~140)
        for i in range(10, 20):
            self.records.append({
                "datetime": self.base_time + timedelta(days=i),
                "sbp": 140 + (i % 3), 
                "dbp": 90 + (i % 3),
                "pp": 50,
                "hr": 80,
                "symptoms": []
            })

    def test_compute_profile(self):
        """测试统计特征计算 (中位数, IQR)"""
        subset = self.records[:5]
        profile = _compute_profile(subset)
        
        self.assertIn("sbp", profile)
        self.assertIn("dbp", profile)
        
        # 120, 121, 120, 121, 120 的中位数应为 120
        self.assertEqual(profile["sbp"]["median"], 120)
        # 波动很小，IQR 应很小
        self.assertLess(profile["sbp"]["iqr"], 5)

    def test_compute_stability(self):
        """测试稳定性评分计算"""
        # 稳定片段
        subset_stable = self.records[:5]
        profile_stable = _compute_profile(subset_stable)
        stability_stable = _compute_stability(profile_stable)
        
        # 不稳定片段 (取头尾差异大的数据)
        # 增加样本量以确保 IQR 计算有效
        subset_unstable = [self.records[0], self.records[1], self.records[15]] 
        profile_unstable = _compute_profile(subset_unstable)
        stability_unstable = _compute_stability(profile_unstable)
        
        # 稳定片段的稳定性分数应更高
        self.assertGreater(stability_stable, stability_unstable)

    def test_slide_windows(self):
        """测试滑动窗口生成"""
        # 窗口大小为 5
        windows = _slide_windows(self.records, 5)
        # 总共 20 条数据，窗口大小 5，应生成 20 - 5 + 1 = 16 个窗口
        self.assertEqual(len(windows), 16)
        
        # 检查第一个窗口索引
        self.assertEqual(windows[0]["start_idx"], 0)
        self.assertEqual(windows[0]["end_idx"], 5)

    def test_gap_penalty(self):
        """测试时间断层惩罚机制"""
        # 构造带有大时间间隔的数据 (第2条和第3条之间隔了29天)
        records_with_gap = [
            {"datetime": self.base_time, "sbp": 120, "dbp": 80, "pp": 40, "hr": 70},
            {"datetime": self.base_time + timedelta(days=1), "sbp": 120, "dbp": 80, "pp": 40, "hr": 70},
            {"datetime": self.base_time + timedelta(days=30), "sbp": 120, "dbp": 80, "pp": 40, "hr": 70},
        ]
        
        windows = _slide_windows(records_with_gap, 3)
        self.assertEqual(len(windows), 1)
        
        # 正常情况下数值完全一致稳定性应为 1.0
        # 但因为有 >7 天的断层，稳定性应受到惩罚而大幅降低
        self.assertLess(windows[0]["stability"], 0.5)

    def test_estimate_user_variability(self):
        """测试用户个体变异性估算"""
        windows = _slide_windows(self.records, 5)
        variability = _estimate_user_variability(windows)
        # 变异性应为正数
        self.assertGreater(variability, 0)

    def test_segment_states(self):
        """测试稳态分段逻辑"""
        windows = _slide_windows(self.records, 5)
        
        # 设置一个较低的阈值，强制将 120 和 140 的数据段分开
        segments, transitions = _segment_states(self.records, windows, dynamic_threshold=5.0)
        
        # 应该至少识别出 2 个不同的稳态段
        self.assertGreaterEqual(len(segments), 2)
        
        # 第一段中位数应接近 120
        self.assertAlmostEqual(segments[0]["profile"]["sbp"]["median"], 120, delta=2)
        # 最后一段中位数应接近 140
        self.assertGreater(segments[-1]["profile"]["sbp"]["median"], 135)

    def test_trajectory_calculation(self):
        """测试轨迹计算逻辑 (Baseline vs Recent)"""
        records = []
        base_time = datetime(2023, 1, 1, 12, 0)
        
        # 构造前5条低值记录 (SBP=110)
        for i in range(5):
            records.append({
                "datetime": base_time + timedelta(days=i),
                "sbp": 110, "dbp": 70, "pp": 40, "hr": 70, "symptoms": []
            })
        
        # 构造后5条高值记录 (SBP=140)
        for i in range(5, 10):
            records.append({
                "datetime": base_time + timedelta(days=i),
                "sbp": 140, "dbp": 90, "pp": 50, "hr": 80, "symptoms": []
            })

        result = analyze_steady_states(records)
        trajectory = result.get("trajectory", {})
        
        self.assertIn("sbp", trajectory)
        
        # 验证 5pt 窗口 (总共10条数据，足够形成 5pt 的 baseline 和 recent)
        found_5pt = False
        for step in trajectory["sbp"]:
            if step["window"] == "5pt":
                found_5pt = True
                self.assertEqual(step["baseline"], 110)
                self.assertEqual(step["recent"], 140)
                self.assertEqual(step["delta"], 30)
                self.assertEqual(step["status"], "up")
        
        self.assertTrue(found_5pt, "Should find 5pt trajectory")

    def test_analyze_steady_states_integration(self):
        """测试主函数集成"""
        result = analyze_steady_states(self.records)
        
        self.assertIn("windows", result)
        self.assertIn("trajectory", result)
        self.assertIn("segments", result)
        
        # 检查是否生成了不同尺度的窗口分析结果
        self.assertIn("5pt", result["windows"])
        self.assertIn("10pt", result["windows"])
        
        # 检查是否生成了轨迹
        self.assertIn("sbp", result["trajectory"])
        
        # 检查是否生成了分段
        self.assertTrue(len(result["segments"]) > 0)

    def test_empty_input(self):
        """测试空输入"""
        result = analyze_steady_states([])
        self.assertEqual(result, {})

    def test_insufficient_data(self):
        """测试数据量不足的情况"""
        # 只有 2 条记录
        short_records = self.records[:2]
        result = analyze_steady_states(short_records)
        
        # 最小窗口是 3pt，所以 windows 应为空
        self.assertEqual(result["windows"], {})
        # 分段基础窗口是 5pt，所以 segments 应为空
        self.assertEqual(result["segments"], [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
