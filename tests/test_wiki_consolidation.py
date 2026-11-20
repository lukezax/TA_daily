"""策略状态汇总：自动识别多日 insight 中相互矛盾的主题。"""

from scripts.consolidate_strategy_state import build_state


def _insight(date, lines):
    return (date, "\n".join(lines))


def test_state_document_has_required_sections():
    text = build_state([_insight("2026-11-01", ["1. B2 平均收益 4.87%，表现最优。"])])
    assert "待人工裁决" in text
    assert "已废弃" in text
    assert "最新洞察" in text


def test_contradictory_theme_is_flagged():
    insights = [
        _insight("2026-07-01", ["1. B1_3分 是唯一有效策略，平均收益 7.81%。"]),
        _insight("2026-09-01", ["1. B1_3分 评分体系失效，平均收益为负。"]),
    ]
    text = build_state(insights)
    assert "B1_3分" in text
    assert "待人工裁决" in text


def test_single_direction_theme_is_not_flagged():
    insights = [
        _insight("2026-11-01", ["1. B2 平均收益 4.87%，表现最优。"]),
        _insight("2026-11-02", ["1. B2 平均收益 5.10%，持续优于 B1。"]),
    ]
    text = build_state(insights)
    section = text.split("## 二、已废弃")[0]
    assert "B2" not in section
