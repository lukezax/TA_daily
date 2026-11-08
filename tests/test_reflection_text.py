"""记忆文本装配的纯函数测试。

这一层不碰网络、不碰数据库，只做「Mongo 里的报告 → 该写什么进记忆」的转换，
所以可以先把行为钉死。
"""
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.reflection_text import (
    ROLE_COLLECTIONS,
    ROLE_FIELDS,
    build_recommendation,
    build_situation,
    compute_raw_change,
    extract_role_text,
    is_correct,
)

# ---------------------------------------------------------------- 抽取


class TestExtractRoleText:
    def test_有角色标记时只取最后一轮(self):
        text = "Bull Analyst: 第一轮内容AAA\n\n中间\n\nBull Analyst: 第二轮内容BBB"
        out = extract_role_text({"bull_researcher": text}, "bull_researcher")
        assert "第二轮内容BBB" in out
        assert "第一轮内容AAA" not in out

    def test_无标记时整段返回(self):
        text = "短辩论稿，没有角色标记"
        out = extract_role_text({"bull_researcher": text}, "bull_researcher")
        assert out == text

    def test_空方用同样的切轮规则(self):
        text = "Bear Analyst: 第一轮XXX\n\nBear Analyst: 第二轮YYY"
        out = extract_role_text({"bear_researcher": text}, "bear_researcher")
        assert "第二轮YYY" in out
        assert "第一轮XXX" not in out

    def test_非辩论角色不切轮(self):
        text = "Bull Analyst: 这段是交易员的计划，不该被切\n\n后半段保留"
        out = extract_role_text({"trader_investment_plan": text}, "trader_investment_plan")
        assert "这段是交易员的计划" in out
        assert "后半段保留" in out

    def test_超长时截断到限额并保留尾部(self):
        text = "A" * 5000 + "TAIL"
        out = extract_role_text({"bull_researcher": text}, "bull_researcher", limit=2000)
        assert len(out) == 2000
        assert out.endswith("TAIL")
        assert out == text[-2000:]

    def test_不超长时原样返回(self):
        text = "短文本"
        assert extract_role_text({"x": text}, "x", limit=2000) == text

    @pytest.mark.parametrize("reports", [None, {}, {"bull_researcher": None}, {"bull_researcher": ""}])
    def test_字段缺失返回空串不抛异常(self, reports):
        assert extract_role_text(reports, "bull_researcher") == ""


# ---------------------------------------------------------------- 收益


class TestComputeRawChange:
    def test_涨一成(self):
        assert compute_raw_change(80.0, 88.0) == pytest.approx(0.1)

    def test_跌一成(self):
        assert compute_raw_change(100.0, 90.0) == pytest.approx(-0.1)

    def test_平盘(self):
        assert compute_raw_change(100.0, 100.0) == pytest.approx(0.0)

    @pytest.mark.parametrize("p0,p1", [(0, 88), (None, 88), (80, None), (-5, 88)])
    def test_价格无效时返回None(self, p0, p1):
        assert compute_raw_change(p0, p1) is None


# ---------------------------------------------------------------- 判对错


class TestIsCorrect:
    def test_多方遇涨判对(self):
        assert is_correct("多方研究员", raw=0.05, pct=0.05) is True

    def test_多方遇跌判错(self):
        assert is_correct("多方研究员", raw=-0.05, pct=-0.05) is False

    def test_空方遇跌判对(self):
        assert is_correct("空方研究员", raw=-0.05, pct=0.05) is True

    def test_空方遇涨判错(self):
        assert is_correct("空方研究员", raw=0.05, pct=-0.05) is False

    def test_买入遇涨判对(self):
        assert is_correct("交易员", raw=0.1, pct=0.1) is True

    def test_卖出遇涨判错(self):
        assert is_correct("交易员", raw=0.1, pct=-0.1) is False

    def test_卖出遇跌判对(self):
        assert is_correct("交易员", raw=-0.1, pct=0.1) is True

    def test_收益刚好为零判为错(self):
        """必须是 > 0，不是 >= 0；零收益等于没判断对。"""
        assert is_correct("交易员", raw=0.0, pct=0.0) is False
        assert is_correct("多方研究员", raw=0.0, pct=0.0) is False
        assert is_correct("空方研究员", raw=0.0, pct=0.0) is False

    def test_缺数据时返回None而不是False(self):
        """缺数据 ≠ 判错，两者在下游文案里要区分。"""
        assert is_correct("多方研究员", raw=None, pct=None) is None
        assert is_correct("交易员", raw=None, pct=None) is None

    def test_空方的判据只用raw不受pct影响(self):
        assert is_correct("空方研究员", raw=-0.1, pct=-0.99) is True

    def test_多方的判据只用raw不受pct影响(self):
        assert is_correct("多方研究员", raw=0.1, pct=-0.99) is True


# ---------------------------------------------------------------- 情境重建


class TestBuildSituation:
    def test_四类报告用双换行拼接(self):
        reports = {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "news_report": "NEWS",
            "fundamentals_report": "FND",
        }
        assert build_situation(reports) == "MKT\n\nSNT\n\nNEWS\n\nFND"

    def test_缺news_report不抛异常(self):
        """97% 的报告没有新闻分析，这条是主路径不是边界。"""
        reports = {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "fundamentals_report": "FND",
        }
        out = build_situation(reports)
        assert out == "MKT\n\nSNT\n\n\n\nFND"

    def test_含缠论时附加在末尾(self):
        reports = {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "news_report": "NEWS",
            "fundamentals_report": "FND",
            "czsc_report": "CZ",
        }
        assert build_situation(reports).endswith("缠论结构分析：\nCZ")

    def test_缠论为空时不附加(self):
        reports = {"market_report": "MKT", "czsc_report": ""}
        assert "缠论" not in build_situation(reports)

    @pytest.mark.parametrize("reports", [None, {}])
    def test_空输入返回空串不抛(self, reports):
        assert build_situation(reports) == ""

    def test_与Reflector的抽取口径逐字一致(self):
        """写入向量与检索向量必须用同一段文本，否则相似度系统性偏移。"""
        from tradingagents.graph.reflection import Reflector

        reflector = Reflector(quick_thinking_llm=None)
        reports = {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "news_report": "NEWS",
            "fundamentals_report": "FND",
            "czsc_report": "CZ",
        }
        state = dict(reports)
        assert build_situation(reports) == reflector._extract_current_situation(state)

    def test_与Reflector口径一致_新闻为空(self):
        """真实场景：Mongo 缺 news_report 时，重建的 state 要补成空串再交给 Reflector。"""
        from tradingagents.graph.reflection import Reflector

        reflector = Reflector(quick_thinking_llm=None)
        reports = {"market_report": "MKT", "sentiment_report": "SNT", "fundamentals_report": "FND"}
        state = {  # 补齐全键，Reflector 用的是直接索引，缺键会 KeyError
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "news_report": "",
            "fundamentals_report": "FND",
        }
        assert build_situation(reports) == reflector._extract_current_situation(state)

    def test_缺新闻时的产出与补空串等价(self):
        base = {"market_report": "MKT", "sentiment_report": "SNT", "fundamentals_report": "FND"}
        assert build_situation(base) == build_situation({**base, "news_report": ""})


# ---------------------------------------------------------------- 组装


class TestBuildRecommendation:
    def _rec(self, **kw):
        base = dict(
            role="多方研究员",
            analysis_date="2026-10-15",
            action="买入",
            raw=0.0235,
            pct=0.0235,
            role_text="我认为被错杀了",
        )
        base.update(kw)
        return build_recommendation(**base)

    def test_含日期决策收益与原文(self):
        out = self._rec()
        assert "2026-10-15" in out
        assert "买入" in out
        assert "+2.35%" in out
        assert "我认为被错杀了" in out

    def test_判对显示正确(self):
        assert "✅正确" in self._rec(role="多方研究员", raw=0.0235, pct=0.0235)

    def test_判错显示错误(self):
        assert "❌错误" in self._rec(role="多方研究员", raw=-0.0235, pct=-0.0235)

    def test_缺数据时判据显示破折号(self):
        out = self._rec(raw=None, pct=None)
        assert "✅正确" not in out
        assert "❌错误" not in out

    def test_收益为负显示负号(self):
        assert "-3.10%" in self._rec(raw=-0.031, pct=-0.031)

    def test_角色名出现在文案里(self):
        assert "空方研究员" in self._rec(role="空方研究员")


# ---------------------------------------------------------------- 常量表


class TestRoleTables:
    def test_五个角色与五个集合一一对应(self):
        assert set(ROLE_FIELDS) == set(ROLE_COLLECTIONS)
        assert len(ROLE_FIELDS) == 5

    def test_字段名与原生反思一致(self):
        assert ROLE_FIELDS["多方研究员"] == "bull_researcher"
        assert ROLE_FIELDS["空方研究员"] == "bear_researcher"
        assert ROLE_FIELDS["交易员"] == "trader_investment_plan"
        assert ROLE_FIELDS["研究总监"] == "research_team_decision"
        assert ROLE_FIELDS["风控"] == "risk_management_decision"

    def test_集合名与原生反思一致(self):
        assert ROLE_COLLECTIONS["多方研究员"] == "bull_memory"
        assert ROLE_COLLECTIONS["空方研究员"] == "bear_memory"
        assert ROLE_COLLECTIONS["交易员"] == "trader_memory"
        assert ROLE_COLLECTIONS["研究总监"] == "invest_judge_memory"
        assert ROLE_COLLECTIONS["风控"] == "risk_manager_memory"
