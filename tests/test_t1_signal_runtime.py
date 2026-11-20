"""信号处理器运行时必须使用新三档标签，不能回退到旧的买卖持有。"""

from pathlib import Path

from tradingagents.graph.signal_processing import SignalProcessor

TA_ROOT = Path(__file__).resolve().parents[1] / "TradingAgents-CN" / "tradingagents"


def test_simple_extraction_recognizes_ignore():
    processor = SignalProcessor(None)
    assert processor._extract_simple_decision("研判结论: **不要看**")["action"] == "不要看"


def test_simple_extraction_recognizes_watch():
    processor = SignalProcessor(None)
    assert processor._extract_simple_decision("研判结论: **关注**")["action"] == "关注"


def test_default_decision_is_watch_not_hold():
    processor = SignalProcessor(None)
    assert processor._get_default_decision()["action"] == "关注"


def test_no_legacy_fallback_in_runtime():
    text = (TA_ROOT / "graph/signal_processing.py").read_text(encoding="utf-8")
    assert "'action': '持有'" not in text
    assert "['买入', '持有', '卖出']" not in text
