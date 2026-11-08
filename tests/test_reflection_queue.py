"""Reflection worker 的 MongoDB 待处理队列测试。

对应方案里「记录待处理 → T+1 扫描成熟项」的流程。
使用独立的测试库，不碰生产数据。
"""
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.reflection_worker import PendingReflectionStore


@pytest.fixture
def store():
    s = PendingReflectionStore("test_reflection_pending")
    s.clear()
    yield s
    s.clear()


class TestRecord:
    def test_记录后可读回(self, store):
        store.record("600150", "2026-10-14", "买入")
        items = store.all_pending()
        assert len(items) == 1
        assert items[0]["stock_symbol"] == "600150"
        assert items[0]["analysis_date"] == "2026-10-14"
        assert items[0]["action"] == "买入"

    def test_持有不被记录(self, store):
        store.record("600150", "2026-10-14", "持有")
        assert store.all_pending() == []

    def test_未知动作不被记录(self, store):
        store.record("600150", "2026-10-14", "观望")
        assert store.all_pending() == []

    def test_同一只股同一天只记录一次(self, store):
        store.record("600150", "2026-10-14", "买入")
        store.record("600150", "2026-10-14", "买入")
        assert len(store.all_pending()) == 1

    def test_缺失股票代码不记录(self, store):
        store.record("", "2026-10-14", "买入")
        assert store.all_pending() == []

    def test_缺失日期不记录(self, store):
        store.record("600150", "", "买入")
        assert store.all_pending() == []


class TestMatured:
    def test_没有后续行情时不算成熟(self, store):
        store.record("600150", "2099-01-01", "买入")
        assert store.matured("600150", "2099-01-01", latest_date="2026-10-14") is False

    def test_分析日之后有行情则成熟(self, store):
        assert store.matured("600150", "2026-10-01", latest_date="2026-10-14") is True

    def test_分析日等于最新行情日不算成熟(self, store):
        """当天决策当天收盘价已知，但没有'后续'，无法判断对错"""
        assert store.matured("600150", "2026-10-14", latest_date="2026-10-14") is False


class TestMarkProcessed:
    def test_标记后不再出现在待处理列表(self, store):
        store.record("600150", "2026-10-01", "买入")
        store.mark_processed("600150", "2026-10-01")
        assert store.all_pending() == []

    def test_标记不存在的项不报错(self, store):
        store.mark_processed("999999", "2026-01-01")

    def test_只标记指定项(self, store):
        store.record("600150", "2026-10-01", "买入")
        store.record("000001", "2026-10-01", "卖出")
        store.mark_processed("600150", "2026-10-01")
        remaining = store.all_pending()
        assert len(remaining) == 1
        assert remaining[0]["stock_symbol"] == "000001"


class TestFailureTracking:
    def test_记录失败后仍留在待处理(self, store):
        store.record("600150", "2026-10-01", "买入")
        store.mark_failed("600150", "2026-10-01", "手机崩溃")
        items = store.all_pending()
        assert len(items) == 1
        assert items[0].get("fail_count") == 1
        assert "手机崩溃" in str(items[0].get("last_error"))

    def test_重复失败累加次数(self, store):
        store.record("600150", "2026-10-01", "买入")
        store.mark_failed("600150", "2026-10-01", "超时")
        assert store.all_pending()[0]["fail_count"] == 1
        store.mark_failed("600150", "2026-10-01", "超时")
        assert store.all_pending()[0]["fail_count"] == 2
        store.mark_failed("600150", "2026-10-01", "超时")
        assert store.all_pending() == []

    def test_超过重试上限的不再返回(self, store):
        store.record("600150", "2026-10-01", "买入")
        for _ in range(5):
            store.mark_failed("600150", "2026-10-01", "持续失败")
        assert store.all_pending() == []

    def test_自定义重试上限(self, store):
        store.record("600150", "2026-10-01", "买入")
        for _ in range(2):
            store.mark_failed("600150", "2026-10-01", "失败")
        assert store.all_pending()[0]["fail_count"] == 2
        store.mark_failed("600150", "2026-10-01", "第三次")
        assert store.all_pending() == []


class TestClear:
    def test_清空后为空(self, store):
        store.record("600150", "2026-10-01", "买入")
        store.clear()
        assert store.all_pending() == []