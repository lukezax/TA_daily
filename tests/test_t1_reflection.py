"""反思系统按 T+1 方向与三档关注等级评分。"""

from pathlib import Path

from pipeline.reflection_worker import (
    REFLECTABLE_ACTIONS,
    compute_realized_return,
    normalize_action,
    should_reflect,
)

TA_ROOT = Path(__file__).resolve().parents[1] / "TradingAgents-CN" / "tradingagents"


def test_all_three_labels_are_reflectable():
    assert set(REFLECTABLE_ACTIONS) == {"关注", "买入", "不要看"}


def test_legacy_hold_normalizes_to_watch():
    assert normalize_action("持有") == "关注"


def test_legacy_sell_normalizes_to_ignore():
    assert normalize_action("卖出") == "不要看"


def test_legacy_labels_are_also_reflectable():
    assert should_reflect("持有") is True
    assert should_reflect("卖出") is True


def test_buy_is_rewarded_when_price_rises():
    assert compute_realized_return("买入", 100.0, 110.0) > 0


def test_watch_is_rewarded_when_price_rises():
    assert compute_realized_return("关注", 100.0, 105.0) > 0


def test_ignore_is_rewarded_when_price_falls():
    assert compute_realized_return("不要看", 100.0, 90.0) > 0


def test_ignore_is_penalized_when_price_rises():
    assert compute_realized_return("不要看", 100.0, 110.0) < 0


def test_reflection_prompt_is_t1_oriented():
    text = (TA_ROOT / "graph/reflection.py").read_text(encoding="utf-8")
    assert "T+1" in text
    assert "HOLD to BUY" not in text
