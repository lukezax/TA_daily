"""分析完成后登记待反思任务的测试。

对应方案里「orchestrator 分析完成 → 记录 (symbol, date, action)」。
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.report_reader import extract_action


class TestExtractAction:
    """decision.action 在库里是中文，需要稳健提取"""

    def test_从decision字段取(self):
        report = {"decision": {"action": "买入"}}
        assert extract_action(report) == "买入"

    def test_缺失decision时回退到recommendation文本(self):
        report = {"recommendation": "投资建议：买入。目标价格：39.5元。"}
        assert extract_action(report) == "买入"

    def test_旧持有映射为关注(self):
        assert extract_action({"recommendation": "投资建议：持有。"}) == "关注"

    def test_旧卖出映射为不要看(self):
        assert extract_action({"recommendation": "建议卖出该股票"}) == "不要看"

    def test_完全无法识别时返回空(self):
        assert extract_action({"recommendation": "暂无明确建议"}) == ""

    def test_空报告返回空(self):
        assert extract_action({}) == ""

    def test_decision优先于recommendation(self):
        report = {"decision": {"action": "持有"}, "recommendation": "投资建议：买入。"}
        assert extract_action(report) == "关注"

    def test_无法识别的动作不返回(self):
        assert extract_action({"decision": {"action": "观望"}}) == ""