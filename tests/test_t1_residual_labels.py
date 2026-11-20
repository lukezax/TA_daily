"""清理仍会污染新三档输出的旧标签（社媒前缀、基本面回退提示、报告模板配色）。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_social_analyst_has_no_final_trade_proposal():
    text = (ROOT / "TradingAgents-CN/tradingagents/agents/analysts/social_media_analyst.py").read_text(encoding="utf-8")
    assert "最终交易提案" not in text


def test_fundamentals_fallback_prompts_use_new_labels():
    text = (ROOT / "TradingAgents-CN/tradingagents/agents/analysts/fundamentals_analyst.py").read_text(encoding="utf-8")
    assert "买入/持有/卖出" not in text


def test_report_template_colors_use_new_labels():
    text = (ROOT / "pipeline/templates/report.html").read_text(encoding="utf-8")
    assert "action == '持有'" not in text
    assert "不要看" in text
