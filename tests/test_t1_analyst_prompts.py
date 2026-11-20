"""分析师提示词必须服务于 T+1 研判，而不是波段交易或旧三档买卖标签。"""

from pathlib import Path

TA_ROOT = Path(__file__).resolve().parents[1] / "TradingAgents-CN" / "tradingagents"


def _read(rel):
    return (TA_ROOT / rel).read_text(encoding="utf-8")


def test_market_analyst_uses_t1_contract_and_new_labels():
    text = _read("agents/analysts/market_analyst.py")
    assert "T1_DECISION_RULE" in text
    assert "买入/持有/卖出" not in text


def test_fundamentals_analyst_drops_swing_horizon_and_old_labels():
    text = _read("agents/analysts/fundamentals_analyst.py")
    assert "持仓周期1-3周" not in text
    assert "买入、持有、卖出" not in text
    assert "T+1" in text


def test_czsc_analyst_uses_three_attention_levels():
    text = _read("agents/analysts/czsc_analyst.py")
    assert "关注/买入/不要看" in text
    assert "买入/持有/观望/减仓" not in text


def test_yangjia_prompt_is_t1_oriented_and_stays_independent():
    """养家 agent 保持独立（不注入下游），但提示词按 T+1 逻辑调整。"""
    text = _read("agents/analysts/yangjia_analyst.py")
    assert "T1_DECISION_RULE" in text
    assert "仓位建议（参照你的赢面仓位表）" not in text
    assert "持仓周期参考：1-3周波段" not in text
    assert "赢面评分=" in text  # 保留原有的固定输出格式
