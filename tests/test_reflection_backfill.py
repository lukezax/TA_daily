"""历史回填的候选筛选测试。

回填的关键风险是「登记了永远算不出结果的条目」——它们会留在队列里
每晚重试、永不出队。所以筛选必须严格：只有「决策时的基准收盘价 + 其后
第一个可交易日的收盘价」都齐的才登记。

实测（2026-10-19）1065 条买入/卖出里 598 条可回填：
  · 503 条分析日当天就有行情
  · 95 条分析日落在周末/节假日 —— 退到之前最近的收盘才救得回来
剩下的 467 条结构性不可能：
  · 283 条分析日之后该股行情已断（大量股票行情只到 20260622）
  · 184 条该股在行情库里根本没有数据（1149 个被分析股票里 221 个无行情）
"""
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.reflection_worker import collect_backfillable, is_backfillable

QUOTES = [
    # 600150：10-13 二、10-14 三、10-16 五、10-19 一（10-15 停牌跳过）
    {"symbol": "600150", "trade_date": "20261013", "close": 100.0},
    {"symbol": "600150", "trade_date": "20261014", "close": 110.0},
    {"symbol": "600150", "trade_date": "20261016", "close": 120.0},
    {"symbol": "600150", "trade_date": "20261019", "close": 130.0},
    {"symbol": "000001", "trade_date": "20261014", "close": 50.0},
]


def doc(symbol, date, action="买入", timestamp=None):
    d = {"stock_symbol": symbol, "analysis_date": date, "decision": {"action": action}}
    if timestamp is not None:
        d["timestamp"] = timestamp
    return d


@pytest.fixture
def store():
    from pipeline.reflection_worker import PendingReflectionStore

    s = PendingReflectionStore("test_reflection_pending_backfill")
    s.clear()
    yield s
    s.clear()


class TestCollectBackfillable:
    """回填登记：只登记「现在就能算出结果」的，避免队列里塞进永不出队的条目。"""

    class FakeColl:
        def __init__(self, rows):
            self.rows = rows

        def find(self, query, projection=None):
            sym = (query.get("symbol") or {})
            if isinstance(sym, dict) and "$in" in sym:
                return [r for r in self.rows if r["symbol"] in sym["$in"]]
            if isinstance(sym, str):
                return [r for r in self.rows if r["symbol"] == sym]
            action = ((query.get("decision") or {}).get("action") or {}).get("$in")
            if action:
                return [r for r in self.rows if ((r.get("decision") or {}).get("action")) in action]
            return list(self.rows)

    class FakeDB:
        def __init__(self, tables):
            self.tables = {k: TestCollectBackfillable.FakeColl(v) for k, v in tables.items()}

        def __getitem__(self, name):
            return self.tables[name]

    def _db(self, reports, quotes):
        return self.FakeDB({"analysis_reports": reports, "stock_daily_quotes": quotes})

    def test_只登记价格成对齐全的(self, store):
        from pipeline.reflection_worker import collect_backfillable

        reports = [
            doc("600150", "2026-10-13"),   # 齐全 → 登记
            doc("600150", "2026-10-19"),   # 分析日是该股最后一行，缺次日 → 跳过
            doc("999999", "2026-10-13"),   # 无行情 → 跳过
            doc("600150", "2026-10-13", "持有"),  # 持有 → 跳过
        ]
        db = self._db(reports, QUOTES)
        assert collect_backfillable(store, db=db) == 1
        assert [i["stock_symbol"] for i in store.all_pending()] == ["600150"]

    def test_试运行只数不改队列(self, store):
        from pipeline.reflection_worker import collect_backfillable

        db = self._db([doc("600150", "2026-10-13")], QUOTES)
        assert collect_backfillable(store, db=db, dry_run=True) == 1
        assert store.all_pending() == []

    def test_重复回填不产生重复条目(self, store):
        from pipeline.reflection_worker import collect_backfillable

        db = self._db([doc("600150", "2026-10-13")], QUOTES)
        collect_backfillable(store, db=db)
        collect_backfillable(store, db=db)
        assert len(store.all_pending()) == 1

    def test_空库返回0(self, store):
        from pipeline.reflection_worker import collect_backfillable

        assert collect_backfillable(store, db=self._db([], [])) == 0


class TestIsBackfillable:
    def test_价格成对齐全才可回填(self):
        assert is_backfillable(doc("600150", "2026-10-13"), QUOTES) is True

    def test_分析日是最后一行时不可回填(self):
        """283 条「分析日之后行情已断」里的一部分 —— 后面再没有行情了。"""
        assert is_backfillable(doc("600150", "2026-10-19"), QUOTES) is False

    def test_分析日早于所有行情时不可回填(self):
        """该股当时还没上市/还没数据，取不到基准价。"""
        assert is_backfillable(doc("600150", "2026-10-12"), QUOTES) is False

    def test_周末分析日退到前一个交易日也能回填(self):
        """95 条这种：analysis_date 是分析**完成时刻**，会落在周末/节假日。
        那天永远没有行情，必须退到之前最近的收盘（10-16 周五）。"""
        assert is_backfillable(doc("600150", "2026-10-17"), QUOTES) is True
        assert is_backfillable(doc("600150", "2026-10-18"), QUOTES) is True

    def test_盘前完成时基准价退到前一天(self):
        """北京 10-13 上午完成（UTC 02:00 = 北京 10:00）：agent 看不到 10-13 的
        收盘，基准价应是 10-12 —— 而 10-12 及之前该股没有行情，所以算不出结果。
        同一天但北京时间收盘后完成（UTC 08:00 = 北京 16:00）就能算。"""
        assert is_backfillable(
            doc("600150", "2026-10-13", timestamp="2026-10-13 02:00:00"), QUOTES
        ) is False
        assert is_backfillable(
            doc("600150", "2026-10-13", timestamp="2026-10-13 08:00:00"), QUOTES
        ) is True

    def test_该股完全无行情时不可回填(self):
        """184 条这种。"""
        assert is_backfillable(doc("999999", "2026-10-13"), QUOTES) is False

    @pytest.mark.parametrize("action", ["持有", "", None])
    def test_非买卖动作不回填(self, action):
        d = doc("600150", "2026-10-13")
        d["decision"] = {"action": action}
        assert is_backfillable(d, QUOTES) is False

    def test_缺decision字段不抛异常(self):
        assert is_backfillable({"stock_symbol": "600150", "analysis_date": "2026-10-13"}, QUOTES) is False

    def test_缺股票或日期不抛异常(self):
        assert is_backfillable({"decision": {"action": "买入"}}, QUOTES) is False

    def test_停牌时用下一个有行情日(self):
        """分析日之后隔了几天才恢复交易，应取恢复那天。"""
        quotes = [
            {"symbol": "600150", "trade_date": "20261013", "close": 100.0},
            {"symbol": "600150", "trade_date": "20261020", "close": 120.0},
        ]
        assert is_backfillable(doc("600150", "2026-10-13"), quotes) is True
