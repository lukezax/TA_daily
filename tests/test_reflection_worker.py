"""Reflection worker 的纯函数逻辑测试。

这些测试对应方案里的「收益算法」表格。任何一个用例失败，
说明策略理解错了，而不是代码写错了。
"""
import os
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.reflection_worker import compute_realized_return, should_reflect


class TestComputeRealizedReturn:
    """收益算法: 买入涨为正, 卖出跌为正, 持有跳过"""

    def test_买入_价格上涨_收益为正(self):
        assert compute_realized_return("买入", 100.0, 110.0) == pytest.approx(0.10)

    def test_买入_价格下跌_收益为负(self):
        assert compute_realized_return("买入", 100.0, 90.0) == pytest.approx(-0.10)

    def test_卖出_价格下跌_收益为正(self):
        assert compute_realized_return("卖出", 100.0, 90.0) == pytest.approx(0.10)

    def test_卖出_价格上涨_收益为负(self):
        assert compute_realized_return("卖出", 100.0, 110.0) == pytest.approx(-0.10)

    def test_价格不变_收益为零(self):
        assert compute_realized_return("买入", 38.11, 38.11) == pytest.approx(0.0)

    def test_持有_返回None表示跳过(self):
        assert compute_realized_return("持有", 100.0, 110.0) is None

    def test_未知动作_返回None(self):
        assert compute_realized_return("观望", 100.0, 110.0) is None

    def test_基准价为零_返回None而非崩溃(self):
        assert compute_realized_return("买入", 0.0, 110.0) is None

    def test_基准价为负_返回None(self):
        assert compute_realized_return("买入", -1.0, 110.0) is None

    def test_缺失价格_返回None(self):
        assert compute_realized_return("买入", None, 110.0) is None
        assert compute_realized_return("买入", 100.0, None) is None

    def test_缺失动作_返回None(self):
        assert compute_realized_return(None, 100.0, 110.0) is None

    def test_不同股价的同比例涨幅_收益相同(self):
        """38元涨10% 和 300元涨10% 必须得到相同收益，否则无法跨股票比较"""
        assert compute_realized_return("买入", 38.0, 41.8) == pytest.approx(0.10)
        assert compute_realized_return("买入", 300.0, 330.0) == pytest.approx(0.10)

    def test_是小数而非百分比数值(self):
        """10% 必须返回 0.1 而不是 10，否则和 LLM 语义冲突"""
        r = compute_realized_return("买入", 100.0, 110.0)
        assert -1.0 < r < 1.0


class TestShouldReflect:
    """跳过「持有」——已确认的决策"""

    def test_持有_跳过(self):
        assert should_reflect("持有") is False

    def test_买入_执行(self):
        assert should_reflect("买入") is True

    def test_卖出_执行(self):
        assert should_reflect("卖出") is True

    def test_未知动作_跳过(self):
        assert should_reflect("观望") is False

    def test_空动作_跳过(self):
        assert should_reflect("") is False

    def test_大小写与空白不影响(self):
        assert should_reflect(" 买入 ") is True