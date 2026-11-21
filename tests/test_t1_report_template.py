"""个股分析报告模板改为 T+1 方向与三档标签，不再展示目标价。"""

from pathlib import Path

from pipeline.models import StockAnalysisResult
from pipeline.report_reader import TradingAgentsReportReader

ROOT = Path(__file__).resolve().parents[1]


def test_template_shows_t1_direction_instead_of_target_price():
    text = (ROOT / "pipeline/templates/report.html").read_text(encoding="utf-8")
    assert "T+1 方向" in text
    assert "目标价" not in text


def test_analysis_result_has_direction_field():
    result = StockAnalysisResult(code="600000.SH", direction="涨")
    assert result.direction == "涨"


def test_final_decision_parser_reads_direction():
    reader = TradingAgentsReportReader(ROOT / "TradingAgents-CN/results")
    decision = reader._parse_final_decision("## 投资建议\n**方向**: 涨\n**行动**: 买入\n")
    assert decision["direction"] == "涨"
