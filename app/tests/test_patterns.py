import unittest
import sys
import os
from datetime import datetime

# 确保可以导入 app 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.engine.patterns import analyze_patterns

class TestPatterns(unittest.TestCase):
    def setUp(self):
        self.base_date = datetime(2023, 1, 1)

    def test_morning_surge_configurable_window(self):
        """测试晨峰时段的可配置性"""
        records = []
        # 夜间基准 (02:00) -> SBP 100
        records.append({"datetime": self.base_date.replace(hour=2, minute=0), "sbp": 100, "dbp": 60})
        
        # 06:00 -> SBP 140 (在默认 5-10 区间内，但在自定义 8-10 区间外)
        records.append({"datetime": self.base_date.replace(hour=6, minute=0), "sbp": 140, "dbp": 90})
        
        # 09:00 -> SBP 110 (在两个区间内)
        records.append({"datetime": self.base_date.replace(hour=9, minute=0), "sbp": 110, "dbp": 70})

        # 1. 使用默认配置 (5-10点)
        # 晨间数据: 140, 110 -> 均值 125
        # 夜间最低: 100
        # 差值: 25 -> mild (>=20)
        res_default = analyze_patterns(records)
        self.assertEqual(res_default["morning_surge"], "mild", "默认时段应包含 06:00 的高值")

        # 2. 使用自定义配置 (8-10点)
        # 晨间数据: 110 -> 均值 110
        # 夜间最低: 100
        # 差值: 10 -> absent (<20)
        # 此时 06:00 的 140 被排除，只计算 09:00 的 110
        config = {"morning_window": (8, 10)}
        res_custom = analyze_patterns(records, config=config)
        self.assertEqual(res_custom["morning_surge"], "absent", "自定义时段应排除 06:00 的高值")

if __name__ == '__main__':
    unittest.main(verbosity=2)