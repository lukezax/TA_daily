"""T+1 研判契约测试：三档标签、禁止交易执行指令、旧标签兼容。"""

from pathlib import Path

from pipeline.labels import LABELS as PIPELINE_LABELS
from pipeline.labels import LEGACY_LABEL_MAP as PIPELINE_LEGACY_MAP
from pipeline.report_reader import ACTION_KEYWORDS, extract_action
from tradingagents.decision_contract import (
    DIRECTIONS,
    LABELS,
    LEGACY_LABEL_MAP,
    T1_DECISION_RULE,
)

TA_ROOT = Path(__file__).resolve().parents[1] / "TradingAgents-CN" / "tradingagents"


def test_labels_are_the_three_attention_levels():
    assert LABELS == ("关注", "买入", "不要看")


def test_directions_are_up_down_flat():
    assert DIRECTIONS == ("涨", "跌", "震荡")


def test_legacy_labels_map_to_new_attention_levels():
    assert LEGACY_LABEL_MAP == {"买入": "买入", "持有": "关注", "卖出": "不要看"}


def test_pipeline_and_tradingagents_contracts_match():
    """两侧常量必须一致，否则 pipeline CLI 与 agent 输出会对不上。"""
    assert PIPELINE_LABELS == LABELS
    assert PIPELINE_LEGACY_MAP == LEGACY_LABEL_MAP


def test_contract_requires_t1_direction_and_forbids_execution_instructions():
    assert "T+1" in T1_DECISION_RULE
    assert "方向" in T1_DECISION_RULE
    assert "目标价" in T1_DECISION_RULE
    assert "止损" in T1_DECISION_RULE
    assert "仓位" in T1_DECISION_RULE


def test_action_keywords_use_new_labels():
    assert ACTION_KEYWORDS == ("关注", "买入", "不要看")


def test_extract_action_maps_legacy_hold_to_watch():
    assert extract_action({"recommendation": "维持持有观察"}) == "关注"


def test_extract_action_maps_legacy_sell_to_ignore():
    assert extract_action({"recommendation": "建议卖出规避"}) == "不要看"


def test_extract_action_reads_new_label_from_decision():
    assert extract_action({"decision": {"action": "买入"}}) == "买入"


def test_trader_prompt_uses_shared_contract_without_trade_order():
    text = (TA_ROOT / "agents/trader/trader.py").read_text(encoding="utf-8")
    assert "T1_DECISION_RULE" in text
    assert "最终交易建议" not in text


def test_signal_processor_schema_uses_new_labels_and_direction():
    text = (TA_ROOT / "graph/signal_processing.py").read_text(encoding="utf-8")
    assert '"action": "关注/买入/不要看"' in text
    assert '"direction": "涨/跌/震荡"' in text
