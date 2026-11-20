"""反思 worker 主循环的测试（不触发网络、不触发真实 LLM）。

写入路径已从「调 graph.reflect_and_remember（5 次 LLM）」换成
「调 MemoryWriter.write_all（1 次 embedding）」，所以这里用假 writer 断言派发。
"""
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")
sys.path.insert(0, "/home/lima/workspace/stock/TradingAgents-CN")

from pipeline.reflection_runner import (
    PendingReflectionStore,
    ReflectionRunner,
    compute_realized_return,
    fetch_decision_prices,
    latest_market_date,
)
from pipeline.reflection_text import ROLE_COLLECTIONS

QUOTES = [
    {"symbol": "600150", "trade_date": "20261014", "close": 100.0},
    {"symbol": "600150", "trade_date": "20261015", "close": 110.0},
    {"symbol": "000001", "trade_date": "20261014", "close": 50.0},
    {"symbol": "000001", "trade_date": "20261015", "close": 45.0},
]


def make_doc(action="买入"):
    return {
        "decision": {"action": action, "confidence": 0.7},
        "reports": {
            "market_report": "MKT",
            "sentiment_report": "SNT",
            "fundamentals_report": "FND",
            "czsc_report": "CZ",
            "bull_researcher": "Bull Analyst: 第一轮旧内容\n\nBull Analyst: 第二轮多方论证",
            "bear_researcher": "Bear Analyst: 第二轮空方论证",
            "trader_investment_plan": "交易员计划正文",
            "research_team_decision": "研究总监裁决正文",
            "risk_management_decision": "风控决议正文",
        },
    }


class FakeReportSource:
    def __init__(self, docs):
        self.docs = docs

    def get(self, stock_symbol, analysis_date):
        return self.docs.get((stock_symbol, analysis_date))


class FakeWriter:
    def __init__(self, seen=()):
        self.calls = []
        self.seen = set(seen)      # 预先「已写过」的情境文本

    def already_written(self, situation):
        return situation in self.seen

    def write_all(self, situation, recommendations):
        self.calls.append((situation, recommendations))
        self.seen.add(situation)
        return len(recommendations)


@pytest.fixture
def store():
    s = PendingReflectionStore("test_reflection_pending_runner")
    s.clear()
    yield s
    s.clear()


def _runner(store, writer=None, docs=None, quotes=None, dry_run=False):
    return ReflectionRunner(
        store=store,
        quotes_provider=lambda: (QUOTES if quotes is None else quotes),
        writer=(lambda: writer) if writer is not None else None,
        report_source=FakeReportSource(docs if docs is not None else {}),
        dry_run=dry_run,
    )


class TestScopedQuoteLoad:
    """行情只按需拉取 —— 全表 150 万行约 1GB，本机可用内存还要和 27B 模型分。"""

    def test_只拉队列里需要的股票与日期(self, store, monkeypatch):
        import pymongo

        sink = {}

        class FakeColl:
            def __init__(self, s):
                self.s = s

            def find(self, query, projection):
                self.s["query"] = query
                return []

        class FakeDB:
            def __init__(self, s):
                self.s = s

            def __getitem__(self, name):
                return FakeColl(self.s)

        class FakeClient:
            def __init__(self, s, *a, **kw):
                self.s = s

            def __getitem__(self, name):
                return FakeDB(self.s)

        monkeypatch.setattr(pymongo, "MongoClient", lambda *a, **kw: FakeClient(sink))

        store.record("600150", "2026-10-14", "买入")
        store.record("000001", "2026-10-13", "买入")
        ReflectionRunner(store=store, quotes_provider=None, writer=lambda: FakeWriter(),
                         report_source=FakeReportSource({})).run_once()

        assert sink["query"]["symbol"] == {"$in": ["000001", "600150"]}
        assert sink["query"]["trade_date"] == {"$gte": "20261013"}

    def test_队列为空时连库都不查(self, store, monkeypatch):
        import pymongo

        calls = []
        monkeypatch.setattr(pymongo, "MongoClient", lambda *a, **kw: calls.append(1))
        assert ReflectionRunner(store=store, quotes_provider=None, writer=lambda: FakeWriter(),
                                report_source=FakeReportSource({})).run_once() == 0
        assert calls == []


class TestRunnerScan:
    def test_没有待处理项时什么都不做(self, store):
        w = FakeWriter()
        assert _runner(store, writer=w).run_once() == 0
        assert w.calls == []

    def test_未成熟的项被跳过(self, store):
        store.record("600150", "20261015", "买入")
        w = FakeWriter()
        assert _runner(store, writer=w, docs={("600150", "20261015"): make_doc()}).run_once() == 0
        assert w.calls == []

    def test_成熟项触发写入一次(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        assert _runner(store, writer=w, docs={("600150", "20261014"): make_doc()}).run_once() == 1
        assert len(w.calls) == 1

    def test_写入五个角色的复盘(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        _runner(store, writer=w, docs={("600150", "20261014"): make_doc()}).run_once()
        _, recs = w.calls[0]
        assert set(recs) == set(ROLE_COLLECTIONS)

    def test_写入的情境来自报告且含缠论(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        _runner(store, writer=w, docs={("600150", "20261014"): make_doc()}).run_once()
        situation, _ = w.calls[0]
        assert situation.startswith("MKT\n\nSNT\n\n\n\nFND")
        assert "缠论结构分析：\nCZ" in situation

    def test_多方复盘只取末轮(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        _runner(store, writer=w, docs={("600150", "20261014"): make_doc()}).run_once()
        _, recs = w.calls[0]
        assert "第二轮多方论证" in recs["多方研究员"]
        assert "第一轮旧内容" not in recs["多方研究员"]

    def test_买入遇涨判对写进文案(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        _runner(store, writer=w, docs={("600150", "20261014"): make_doc("买入")}).run_once()
        _, recs = w.calls[0]
        assert "✅正确" in recs["交易员"]
        assert "+10.00%" in recs["交易员"]

    def test_卖出遇涨判错写进文案(self, store):
        store.record("600150", "20261014", "卖出")
        w = FakeWriter()
        _runner(store, writer=w, docs={("600150", "20261014"): make_doc("卖出")}).run_once()
        _, recs = w.calls[0]
        assert "❌错误" in recs["交易员"]
        assert "-10.00%" in recs["交易员"]

    def test_以Mongo的决策为准而非队列里的动作(self, store):
        """队列里的 action 是从文本正则抽的，可能不准，必须回到 Mongo 取权威值。"""
        store.record("600150", "20261014", "卖出")  # 故意写错
        w = FakeWriter()
        _runner(store, writer=w, docs={("600150", "20261014"): make_doc("买入")}).run_once()
        _, recs = w.calls[0]
        assert "系统决策：买入" in recs["交易员"]
        assert "+10.00%" in recs["交易员"]

    def test_Mongo无决策时回退到队列里的动作(self, store):
        store.record("600150", "20261014", "买入")
        doc = make_doc()
        doc["decision"] = {}
        w = FakeWriter()
        _runner(store, writer=w, docs={("600150", "20261014"): doc}).run_once()
        _, recs = w.calls[0]
        assert "系统决策：买入" in recs["交易员"]

    def test_权威动作为持有时映射为关注并写记忆出队(self, store):
        """旧「持有」映射为「关注」后同样可学习；以 Mongo 权威动作为准。"""
        store.record("600150", "20261014", "买入")  # 队列以为买入
        w = FakeWriter()
        assert _runner(store, writer=w, docs={("600150", "20261014"): make_doc("持有")}).run_once() == 1
        assert len(w.calls) == 1
        assert store.all_pending() == []

    def test_权威动作与队列方向相反时以Mongo为准(self, store):
        """队列说卖出、Mongo 说买入 → 必须按买入算，否则收益符号整个反了。"""
        store.record("600150", "20261014", "卖出")
        w = FakeWriter()
        _runner(store, writer=w, docs={("600150", "20261014"): make_doc("买入")}).run_once()
        _, recs = w.calls[0]
        assert "系统决策：买入" in recs["交易员"]
        assert "✅正确" in recs["交易员"]  # 买入遇涨

    def test_处理成功后从队列移除(self, store):
        store.record("600150", "20261014", "买入")
        _runner(store, writer=FakeWriter(), docs={("600150", "20261014"): make_doc()}).run_once()
        assert store.all_pending() == []

    def test_找不到报告时跳过且不记失败(self, store):
        """报告还没落库属于「数据未到」，不是「执行失败」。"""
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        assert _runner(store, writer=w, docs={}).run_once() == 0
        assert w.calls == []
        remaining = store.all_pending()
        assert len(remaining) == 1
        assert remaining[0].get("fail_count", 0) == 0

    def test_取不到价格时不标记完成(self, store):
        store.record("999999", "20261014", "买入")
        w = FakeWriter()
        assert _runner(store, writer=w, docs={("999999", "20261014"): make_doc()}).run_once() == 0
        assert w.calls == []

    def test_写入抛异常时记失败并继续下一只(self, store):
        store.record("600150", "20261014", "买入")
        store.record("000001", "20261014", "卖出")
        docs = {
            ("600150", "20261014"): make_doc("买入"),
            ("000001", "20261014"): make_doc("卖出"),
        }

        class Flaky(FakeWriter):
            def __init__(self):
                super().__init__()
                self.n = 0

            def write_all(self, situation, recommendations):
                self.n += 1
                if self.n == 1:
                    raise RuntimeError("ChromaDB 挂了")
                return super().write_all(situation, recommendations)

        assert _runner(store, writer=Flaky(), docs=docs).run_once() == 1
        remaining = store.all_pending()
        assert len(remaining) == 1
        assert remaining[0]["stock_symbol"] == "600150"
        assert remaining[0]["fail_count"] == 1

    def test_行情数据获取失败时整轮放弃(self, store):
        store.record("600150", "20261014", "买入")

        def boom():
            raise RuntimeError("Mongo挂了")

        w = FakeWriter()
        r = ReflectionRunner(store=store, quotes_provider=boom,
                             writer=lambda: w, report_source=FakeReportSource({}))
        assert r.run_once() == 0
        assert w.calls == []
        assert len(store.all_pending()) == 1

    def test_没有待处理项时不构造写入器(self, store):
        """空队列的夜里不该去连 ChromaDB —— 少一次跨进程撞锁的机会。"""
        built = []

        def factory():
            built.append(1)
            return FakeWriter()

        r = ReflectionRunner(store=store, quotes_provider=lambda: QUOTES,
                             writer=factory, report_source=FakeReportSource({}))
        assert r.run_once() == 0
        assert built == []

    def test_有需要时才构造写入器(self, store):
        store.record("600150", "20261014", "买入")
        built = []

        def factory():
            built.append(1)
            return FakeWriter()

        _runner = ReflectionRunner(store=store, quotes_provider=lambda: QUOTES,
                                   writer=factory,
                                   report_source=FakeReportSource({("600150", "20261014"): make_doc()}))
        assert _runner.run_once() == 1
        assert built == [1]

    def test_未配置writer时抛错(self, store):
        store.record("600150", "20261014", "买入")
        r = ReflectionRunner(store=store, quotes_provider=lambda: QUOTES,
                             report_source=FakeReportSource({("600150", "20261014"): make_doc()}))
        with pytest.raises(RuntimeError):
            r.run_once()


class TestSkipAlreadyWritten:
    """已经写进记忆库的条目要直接出队，不能重写。

    `collect_backfillable` 会把**所有**算得出结果的决策重新登记（含早就写好的 582 条），
    而成功的条目已经出队 —— 不拦住就会重新 embedding（一次 22 秒）并写成**重复条目**。
    """

    def test_已在记忆库里的条目出队且不重复写(self, store):
        from pipeline.reflection_text import build_situation

        store.record("600150", "20261014", "买入")
        doc = make_doc("买入")
        w = FakeWriter(seen=[build_situation(doc["reports"])])

        assert _runner(store, writer=w, docs={("600150", "20261014"): doc}).run_once() == 1
        assert w.calls == []                 # 没有重复写
        assert store.all_pending() == []     # 但出队了，不会永远滞留

    def test_没写过的照常写入(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter(seen=["某条别的情境"])

        assert _runner(store, writer=w, docs={("600150", "20261014"): make_doc("买入")}).run_once() == 1
        assert len(w.calls) == 1

    def test_试运行时也不重复写(self, store):
        from pipeline.reflection_text import build_situation

        store.record("600150", "20261014", "买入")
        doc = make_doc("买入")
        w = FakeWriter(seen=[build_situation(doc["reports"])])
        r = _runner(store, writer=w, docs={("600150", "20261014"): doc}, dry_run=True)

        assert r.run_once() == 1
        assert w.calls == []
        assert len(store.all_pending()) == 1   # 试运行不动队列


class TestRunnerDryRun:
    def test_试运行不写记忆(self, store):
        store.record("600150", "20261014", "买入")
        w = FakeWriter()
        r = _runner(store, writer=w, docs={("600150", "20261014"): make_doc()}, dry_run=True)
        assert r.run_once() == 1
        assert w.calls == []

    def test_试运行不清空队列(self, store):
        store.record("600150", "20261014", "买入")
        r = _runner(store, writer=FakeWriter(),
                    docs={("600150", "20261014"): make_doc()}, dry_run=True)
        r.run_once()
        assert len(store.all_pending()) == 1


class TestMongoReportSource:
    def test_真实库能取到报告与决策(self):
        from pipeline.reflection_worker import MongoReportSource

        doc = MongoReportSource().get("002920", "2026-10-15")
        assert doc is not None
        assert (doc.get("reports") or {}).get("market_report")
        assert (doc.get("decision") or {}).get("action")

    def test_不存在的组合返回None(self):
        from pipeline.reflection_worker import MongoReportSource

        assert MongoReportSource().get("000000", "1900-01-01") is None


class TestMongoReportSourceDateTolerance:
    """队列日期 ≠ 报告日期时也要能取到，否则条目永远留在队列里空转。

    队列里的 analysis_date 是「流水线登记那一刻」（`_enqueue_reflections` 用
    `date.today()`），报告里的 analysis_date 是「该股分析完成那一刻」。跨午夜
    的批次两侧会错开一天（实测真有：某进程 22:39 起跑、跑到次日）。
    """

    class FakeColl:
        def __init__(self, docs):
            self.docs = docs

        def find_one(self, query, projection=None):
            for d in self.docs:
                if (d["stock_symbol"] == query["stock_symbol"]
                        and d["analysis_date"] == query["analysis_date"]):
                    return dict(d)
            return None

        def find(self, query, projection=None):
            cond = query["analysis_date"]
            out = []
            for d in self.docs:
                if d["stock_symbol"] != query["stock_symbol"]:
                    continue
                if isinstance(cond, dict):
                    if not (cond["$gte"] <= d["analysis_date"] <= cond["$lte"]):
                        continue
                elif cond != d["analysis_date"]:
                    continue
                out.append(dict(d))
            return out

    def _src(self, docs, tolerance_days=3):
        from pipeline.reflection_worker import MongoReportSource

        src = MongoReportSource.__new__(MongoReportSource)   # 不连真库
        src._coll = self.FakeColl(docs)
        src._tolerance_days = tolerance_days
        return src

    @staticmethod
    def _report(symbol, date, action):
        return {"stock_symbol": symbol, "analysis_date": date, "decision": {"action": action}}

    def test_精确命中优先(self):
        src = self._src([
            self._report("600150", "2026-10-15", "买入"),
            self._report("600150", "2026-10-16", "卖出"),
        ])
        assert src.get("600150", "2026-10-16")["decision"]["action"] == "卖出"

    def test_队列日期比报告早一天时能取到(self):
        """典型场景：分析跨午夜完成，报告记在次日。"""
        src = self._src([self._report("600150", "2026-10-19", "买入")])
        doc = src.get("600150", "2026-10-18")
        assert doc is not None
        assert doc["decision"]["action"] == "买入"

    def test_队列日期比报告晚一天时能取到(self):
        src = self._src([self._report("600150", "2026-10-17", "卖出")])
        assert src.get("600150", "2026-10-18")["decision"]["action"] == "卖出"

    def test_多个候选取最近的那个(self):
        src = self._src([
            self._report("600150", "2026-10-16", "卖出"),
            self._report("600150", "2026-10-20", "买入"),
        ])
        assert src.get("600150", "2026-10-17")["decision"]["action"] == "卖出"

    def test_错开超过容差就返回None(self):
        src = self._src([self._report("600150", "2026-10-25", "买入")])
        assert src.get("600150", "2026-10-18") is None

    def test_容差不会串到别的股票(self):
        src = self._src([self._report("000001", "2026-10-19", "买入")])
        assert src.get("600150", "2026-10-18") is None

    def test_日期非法时不抛异常(self):
        src = self._src([])
        assert src.get("600150", "坏日期") is None

    def test_取到的文档带上timestamp供判盘前盘后(self):
        src = self._src([
            {"stock_symbol": "600150", "analysis_date": "2026-10-19",
             "decision": {"action": "买入"}, "timestamp": "2026-10-19 02:00:00"},
        ])
        assert src.get("600150", "2026-10-18")["timestamp"] == "2026-10-19 02:00:00"


class TestPureHelpers:
    """保留原有纯函数的回归。"""

    def test_收益方向(self):
        assert compute_realized_return("买入", 100.0, 110.0) == pytest.approx(0.1)
        assert compute_realized_return("卖出", 100.0, 110.0) == pytest.approx(-0.1)
        assert compute_realized_return("持有", 100.0, 110.0) == pytest.approx(0.1)  # 旧持有→关注

    def test_取价(self):
        p0, p1 = fetch_decision_prices(QUOTES, "600150", "20261014")
        assert (p0, p1) == (100.0, 110.0)

    def test_最新行情日(self):
        assert latest_market_date(QUOTES) == "20261015"
