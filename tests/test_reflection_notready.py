"""价格未到齐时的处理：数据滞后是暂时的，不能当成失败。

这是写入路径改造后**特意保留**的一组不变量测试：
「数据没到」会一直留在队列里等，fail_count 不能涨；
只有「真的执行出错」才计失败 —— 否则某只股行情同步慢几天，
就会被误判成坏任务反复重试甚至丢弃。
"""
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.reflection_runner import ReflectionRunner
from pipeline.reflection_worker import MAX_FAILURES, PendingReflectionStore

PARTIAL = [{"symbol": "600150", "trade_date": "20261014", "close": 100.0}]
FULL = PARTIAL + [{"symbol": "600150", "trade_date": "20261015", "close": 110.0}]

DOC = {
    "decision": {"action": "买入"},
    "reports": {"market_report": "MKT", "bull_researcher": "Bull Analyst: 多方"},
}


class FakeReportSource:
    def __init__(self, docs=None):
        self.docs = docs if docs is not None else {}

    def get(self, stock_symbol, analysis_date):
        return self.docs.get((stock_symbol, analysis_date))


class FakeWriter:
    def __init__(self):
        self.calls = []

    def already_written(self, situation):
        return False        # 本文件只关心「数据没到齐」的语义，去重交给 writer 自己的测试

    def write_all(self, situation, recommendations):
        self.calls.append((situation, recommendations))
        return len(recommendations)


@pytest.fixture
def store():
    s = PendingReflectionStore("test_reflection_pending_notready")
    s.clear()
    yield s
    s.clear()


def _runner(store, quotes, writer=None, docs=None):
    return ReflectionRunner(
        store=store,
        quotes_provider=lambda: quotes,
        writer=(lambda: writer) if writer is not None else None,
        report_source=FakeReportSource(docs if docs is not None else {("600150", "20261014"): DOC}),
    )


class TestPriceNotReadyYet:
    def test_T1价格缺失时留在队列(self, store):
        store.record("600150", "20261014", "买入")
        assert _runner(store, PARTIAL, FakeWriter()).run_once() == 0
        assert len(store.all_pending()) == 1

    def test_T1价格缺失不计失败次数(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        r = _runner(store, PARTIAL, w)
        for _ in range(5):
            r.run_once()
        assert store.all_pending()[0].get("fail_count", 0) == 0
        assert w.calls == []

    def test_分析日本身无价格时也不算失败(self, store):
        """该股行情完全没同步到分析日。"""
        store.record("600150", "20261013", "买入")
        r = _runner(store, PARTIAL, FakeWriter(),
                    docs={("600150", "20261013"): DOC})
        for _ in range(4):
            r.run_once()
        assert store.all_pending()[0].get("fail_count", 0) == 0

    def test_数据到齐后能正常处理(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        assert _runner(store, PARTIAL, w).run_once() == 0
        assert len(store.all_pending()) == 1

        assert _runner(store, FULL, w).run_once() == 1
        assert len(w.calls) == 1
        assert "+10.00%" in w.calls[0][1]["交易员"]
        assert store.all_pending() == []

    def test_写入异常仍计失败(self, store):
        """区分「数据没到」和「执行出错」。"""
        store.record("600150", "20261014", "买入")

        class Boom(FakeWriter):
            def write_all(self, situation, recommendations):
                raise RuntimeError("ChromaDB 炸了")

        _runner(store, FULL, Boom()).run_once()
        assert store.all_pending()[0]["fail_count"] == 1


class TestResetFailures:
    """失败计数必须能人工归零。

    fail_count 到 MAX_FAILURES 就永久不再重试（防毒丸数据），但 embedding 服务
    抽风会让**整批**条目一起失败 —— 那不是条目的错。实测 2026-10-22 有 293 条
    卡在 fail_count=2，当晚再失败一次就会全部静默消失、记忆永久缺失。
    """

    def test_归零并返回被归零的条数(self, store):
        store.record("600150", "20261014", "买入")
        store.record("600151", "20261014", "卖出")
        store.mark_failed("600150", "20261014", "服务挂了")
        store.mark_failed("600150", "20261014", "服务又挂了")
        store.mark_failed("600151", "20261014", "服务挂了")

        assert store.reset_failures() == 2
        assert all(i["fail_count"] == 0 for i in store.all_pending())

    def test_已到丢弃上限的条目重新可重试(self, store):
        """这是这个开关存在的理由：否则条目一旦到 3 次就再也捞不回来。"""
        store.record("600150", "20261014", "买入")
        for _ in range(MAX_FAILURES):
            store.mark_failed("600150", "20261014", "服务挂了")
        assert store.all_pending() == []          # 已被过滤掉，永不重试

        assert store.reset_failures() == 1
        assert len(store.all_pending()) == 1      # 捞回来了

    def test_归零后重新从0计数(self, store):
        store.record("600150", "20261014", "买入")
        store.mark_failed("600150", "20261014", "第一次")
        store.reset_failures()
        store.mark_failed("600150", "20261014", "第二次")
        assert store.all_pending()[0]["fail_count"] == 1

    def test_不动条目本身的内容(self, store):
        store.record("600150", "20261014", "买入")
        store.mark_failed("600150", "20261014", "服务挂了")
        store.reset_failures()

        item = store.all_pending()[0]
        assert item["stock_symbol"] == "600150"
        assert item["analysis_date"] == "20261014"
        assert item["action"] == "买入"

    def test_没有失败条目时返回0(self, store):
        store.record("600150", "20261014", "买入")
        assert store.reset_failures() == 0

    def test_空队列不报错(self, store):
        assert store.reset_failures() == 0
