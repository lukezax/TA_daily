"""
测试报告一致性校验器 (ReportValidator)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from tradingagents.graph.report_validator import ReportValidator


class MockLLM:
    """Mock LLM for testing"""
    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0

    def invoke(self, messages):
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
        else:
            response = "修正后的分析内容"
        self.call_count += 1

        class MockResponse:
            def __init__(self, content):
                self.content = content
        return MockResponse(response)


class TestExtractGroundTruth:
    """测试 ground truth 提取"""

    def test_extract_name_and_price(self):
        validator = ReportValidator(llm=None)
        market_report = """# **爱乐达（300696）技术分析报告**

## 基本信息
当前价格：40.25
"""
        result = validator.extract_ground_truth(market_report, "300696")
        assert result["name"] == "爱乐达"
        assert result["price"] == 40.25
        assert result["code"] == "300696"

    def test_extract_with_yen_symbol(self):
        validator = ReportValidator(llm=None)
        market_report = """# **华勤技术（603296）技术分析报告**

当前价格: ¥85.50
"""
        result = validator.extract_ground_truth(market_report, "603296")
        assert result["name"] == "华勤技术"
        assert result["price"] == 85.50

    def test_extract_empty_report(self):
        validator = ReportValidator(llm=None)
        result = validator.extract_ground_truth("", "300696")
        assert result["name"] == "股票300696"
        assert result["price"] == 0.0

    def test_extract_no_price(self):
        validator = ReportValidator(llm=None)
        market_report = "# **爱乐达（300696）技术分析报告**\n没有价格信息"
        result = validator.extract_ground_truth(market_report, "300696")
        assert result["name"] == "爱乐达"
        assert result["price"] == 0.0


class TestDetectErrors:
    """测试错误检测"""

    def test_no_errors_in_correct_report(self):
        validator = ReportValidator(llm=None)
        ground_truth = {"code": "300696", "name": "爱乐达", "price": 40.0}
        content = "爱乐达（300696）是一家优秀的公司，目标价位：¥45.00"
        errors = validator.detect_errors(content, ground_truth)
        assert len(errors) == 0

    def test_detect_wrong_price_deviation(self):
        validator = ReportValidator(llm=None)
        ground_truth = {"code": "300696", "name": "爱乐达", "price": 40.0}
        # 目标价 7.15 偏离 40.0 超过 50%
        content = "基于分析，目标价位：¥7.15"
        errors = validator.detect_errors(content, ground_truth)
        assert len(errors) > 0
        assert errors[0]["type"] == "wrong_price"
        assert errors[0]["wrong"] == 7.15
        assert errors[0]["correct"] == 40.0

    def test_no_error_for_reasonable_target(self):
        validator = ReportValidator(llm=None)
        ground_truth = {"code": "300696", "name": "爱乐达", "price": 40.0}
        # 目标价 48.0 偏离 40.0 只有 20%，在合理范围内
        content = "基于分析，目标价位：¥48.00"
        errors = validator.detect_errors(content, ground_truth)
        assert len(errors) == 0

    def test_detect_wrong_name(self):
        validator = ReportValidator(llm=None)
        ground_truth = {"code": "300696", "name": "爱乐达", "price": 40.0}
        # 使用了错误的公司名
        content = "300696）（爱丽家居）是一家公司"
        errors = validator.detect_errors(content, ground_truth)
        assert any(e["type"] == "wrong_name" for e in errors)

    def test_empty_content(self):
        validator = ReportValidator(llm=None)
        ground_truth = {"code": "300696", "name": "爱乐达", "price": 40.0}
        errors = validator.detect_errors("", ground_truth)
        assert len(errors) == 0

    def test_no_price_in_ground_truth_skips_price_check(self):
        validator = ReportValidator(llm=None)
        ground_truth = {"code": "300696", "name": "爱乐达", "price": 0.0}
        content = "目标价位：¥7.15"
        errors = validator.detect_errors(content, ground_truth)
        # price is 0, so price check is skipped
        assert len(errors) == 0


class TestValidateAndRetry:
    """测试校验和重试逻辑"""

    def test_passes_when_no_errors(self):
        validator = ReportValidator(llm=MockLLM())
        state = {
            "market_report": "# **爱乐达（300696）技术分析报告**\n当前价格：40.00",
            "company_of_interest": "300696",
            "investment_plan": "爱乐达（300696）是一家优秀的公司，目标价位：¥45.00",
        }
        result = validator.validate_and_retry(state, "investment_plan")
        assert "_validation_failed" not in result

    def test_retries_on_error_and_succeeds(self):
        # LLM returns corrected content on first retry
        corrected = "爱乐达（300696）是一家优秀的公司，目标价位：¥45.00"
        validator = ReportValidator(llm=MockLLM(responses=[corrected]))
        state = {
            "market_report": "# **爱乐达（300696）技术分析报告**\n当前价格：40.00",
            "company_of_interest": "300696",
            "investment_plan": "基于分析，目标价位：¥7.15",  # wrong price
        }
        result = validator.validate_and_retry(state, "investment_plan")
        assert "_validation_failed" not in result
        assert result["investment_plan"] == corrected

    def test_fails_after_max_retries(self):
        # LLM keeps returning wrong content
        wrong = "基于分析，目标价位：¥7.15"
        validator = ReportValidator(llm=MockLLM(responses=[wrong, wrong, wrong]))
        state = {
            "market_report": "# **爱乐达（300696）技术分析报告**\n当前价格：40.00",
            "company_of_interest": "300696",
            "investment_plan": "基于分析，目标价位：¥7.15",
        }
        result = validator.validate_and_retry(state, "investment_plan")
        assert result.get("_validation_failed") is True
        assert "修正仍存在数据错误" in result.get("_validation_failure_reason", "")

    def test_skips_when_no_ground_truth_price(self):
        validator = ReportValidator(llm=MockLLM())
        state = {
            "market_report": "没有价格信息的报告",
            "company_of_interest": "300696",
            "investment_plan": "目标价位：¥7.15",
        }
        result = validator.validate_and_retry(state, "investment_plan")
        # No ground truth price, so validation is skipped
        assert "_validation_failed" not in result

    def test_skips_empty_content(self):
        validator = ReportValidator(llm=MockLLM())
        state = {
            "market_report": "# **爱乐达（300696）技术分析报告**\n当前价格：40.00",
            "company_of_interest": "300696",
            "investment_plan": "",
        }
        result = validator.validate_and_retry(state, "investment_plan")
        assert "_validation_failed" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
