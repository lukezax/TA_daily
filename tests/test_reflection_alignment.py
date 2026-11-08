"""reflection.py 的两处口径修正测试。

对应方案里的「两个必须修正的点」：
1. prompt 必须写明收益单位是百分比
2. 写入的 situation 必须与查询(trader.py)口径一致，都含缠论
"""
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock/TradingAgents-CN")

from tradingagents.graph.reflection import Reflector


@pytest.fixture
def reflector():
    return Reflector(quick_thinking_llm=None)


class TestPromptStatesPercentage:
    def test_prompt_明确说明收益是百分比(self, reflector):
        prompt = reflector.reflection_system_prompt.lower()
        assert "percentage" in prompt

    def test_prompt_说明正负号含义(self, reflector):
        prompt = reflector.reflection_system_prompt
        assert "positive" in prompt.lower()
        assert "negative" in prompt.lower()


class TestSituationMatchesQueryPath:
    def test_包含缠论报告(self, reflector):
        state = {
            "market_report": "市场报告内容",
            "sentiment_report": "情绪报告内容",
            "news_report": "新闻报告内容",
            "fundamentals_report": "基本面报告内容",
            "czsc_report": "缠论结构内容XYZ",
        }
        situation = reflector._extract_current_situation(state)
        assert "缠论结构内容XYZ" in situation

    def test_包含全部四类基础报告(self, reflector):
        state = {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "news_report": "NEWS",
            "fundamentals_report": "FND",
            "czsc_report": "CZ",
        }
        situation = reflector._extract_current_situation(state)
        for token in ("MKT", "SNT", "NEWS", "FND", "CZ"):
            assert token in situation

    def test_缺少缠论字段时不报错(self, reflector):
        state = {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "news_report": "NEWS",
            "fundamentals_report": "FND",
        }
        situation = reflector._extract_current_situation(state)
        assert "MKT" in situation

    def test_缠论为空字符串时不影响其余内容(self, reflector):
        state = {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "news_report": "NEWS",
            "fundamentals_report": "FND",
            "czsc_report": "",
        }
        situation = reflector._extract_current_situation(state)
        assert "MKT" in situation and "SNT" in situation

    def test_与trader查询口径一致(self, reflector):
        """trader.py:40 用 \\n\\n 拼接，reflection 必须一致"""
        state = {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "news_report": "NEWS",
            "fundamentals_report": "FND",
            "czsc_report": "CZ",
        }
        situation = reflector._extract_current_situation(state)
        expected_prefix = "MKT\n\nSNT\n\nNEWS\n\nFND"
        assert situation.startswith(expected_prefix)