"""orchestrator 登记待反思任务的集成测试（不触发真实 LLM）。"""
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.models import StockAnalysisResult
from pipeline.reflection_worker import PendingReflectionStore


@pytest.fixture
def store():
    s = PendingReflectionStore("test_reflection_pending_orch")
    s.clear()
    yield s
    s.clear()


def _result(code, rec, status="completed"):
    return StockAnalysisResult(code=code, status=status, recommendation=rec)


class TestRecordPendingAfterAnalysis:
    def test_分析完成后登记(self, store):
        from pipeline.orchestrator import record_pending_reflections

        results = {
            "600150": _result("600150", "投资建议：买入。目标价格：40元。"),
            "000001": _result("000001", "投资建议：持有。"),
        }
        n = record_pending_reflections(results, store, "2026-10-14")
        assert n == 1
        assert store.all_pending()[0]["stock_symbol"] == "600150"

    def test_空结果不报错(self, store):
        from pipeline.orchestrator import record_pending_reflections

        assert record_pending_reflections({}, store, "2026-10-14") == 0

    def test_登记失败不影响主流程(self, store):
        """登记是副作用，炸了也不能影响分析结果返回"""
        from pipeline.orchestrator import record_pending_reflections

        with patch.object(store, "record", side_effect=RuntimeError("db挂了")):
            results = {"600150": _result("600150", "买入")}
            try:
                record_pending_reflections(results, store, "2026-10-14")
            except RuntimeError:
                pytest.fail("登记失败不应向上抛出")

    def test_关闭开关时不登记(self, store):
        from pipeline.orchestrator import record_pending_reflections

        n = record_pending_reflections(
            {"600150": _result("600150", "买入")}, store, "2026-10-14", enabled=False
        )
        assert n == 0
        assert store.all_pending() == []

    def test_开启开关时登记(self, store):
        from pipeline.orchestrator import record_pending_reflections

        n = record_pending_reflections(
            {"600150": _result("600150", "买入")}, store, "2026-10-14", enabled=True
        )
        assert n == 1