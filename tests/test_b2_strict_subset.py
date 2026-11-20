"""B2 严格版必须建立在宽松版条件之上（严格 ⊆ 宽松）。

回归测试：原实现用 J_LAST<13 作为严格条件，比宽松的 J_LAST<0 更松，
导致「严格通过但宽松不通过」。现有 168 份 CSV 中有 439 条此类记录。
"""

import pytest

from stock_filter_b2 import B2_STRATEGY_CONFIG, b2_decision


def test_strict_never_passes_when_base_condition_fails():
    """宽松基础条件不满足时，严格版也必须不通过。"""
    strict, loose = b2_decision(False, True, True, True, True, True, True)
    assert strict is False
    assert loose is False


def test_strict_requires_all_extra_conditions():
    """宽松通过但额外条件不满足时，只能算宽松通过。"""
    strict, loose = b2_decision(True, True, True, True, False, True, True)
    assert strict is False
    assert loose is True


def test_strict_and_loose_both_pass_when_all_conditions_hold():
    strict, loose = b2_decision(True, True, True, True, True, True, True)
    assert strict is True
    assert loose is True


def test_strict_threshold_matches_loose_threshold():
    """严格版不应使用比宽松版更松的 J_LAST 阈值。"""
    assert B2_STRATEGY_CONFIG["j_strict_threshold"] == B2_STRATEGY_CONFIG["j_loose_threshold"]
