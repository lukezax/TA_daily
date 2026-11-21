"""分析结果解析：容忍 null target_price，并从推理文本补齐 T+1 方向。"""

from pipeline.analysis_client import parse_result_payload


def test_null_target_price_does_not_break_parsing():
    data = {
        "decision": {
            "action": "不要看",
            "confidence": 0.65,
            "risk_score": 0.5,
            "target_price": None,
            "reasoning": "未形成明确上涨信号，T+1判断为震荡，暂不纳入观察。",
        },
        "reports": {},
    }
    result = parse_result_payload(data, "600267.SH", 1.0)
    assert result.status == "completed"
    assert result.recommendation == "不要看"
    assert result.target_price == 0.0
    assert result.confidence_score == 65.0


def test_recommendation_is_short_label_not_long_sentence():
    data = {
        "decision": {"action": "不要看", "reasoning": "T+1判断为震荡，暂不纳入观察。"},
        "recommendation": "投资建议：不要看。决策依据：均线走弱、量能不足。",
    }
    result = parse_result_payload(data, "600267.SH", 1.0)
    assert result.recommendation == "不要看"
    assert "均线走弱" in result.summary


def test_direction_falls_back_to_reasoning_text():
    data = {
        "decision": {
            "action": "买入",
            "confidence": 0.7,
            "risk_score": 0.4,
            "reasoning": "量价配合良好，T+1判断为上涨。",
        }
    }
    result = parse_result_payload(data, "600000.SH", 1.0)
    assert result.direction == "涨"
