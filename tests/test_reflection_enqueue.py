"""分析结果登记进待反思队列的测试。"""
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.models import StockAnalysisResult
from pipeline.reflection_worker import (
    PendingReflectionStore,
    enqueue_reflection,
    normalize_symbol,
)


@pytest.fixture
def store():
    s = PendingReflectionStore("test_reflection_pending_enqueue")
    s.clear()
    yield s
    s.clear()


def _result(code, rec, status="completed"):
    return StockAnalysisResult(code=code, status=status, recommendation=rec)


class TestEnqueueReflection:
    def test_买入建议被登记(self, store):
        n = enqueue_reflection([_result("600150", "投资建议：买入。目标价格：40元。")], store)
        assert n == 1
        assert store.all_pending()[0]["stock_symbol"] == "600150"

    def test_卖出建议被登记(self, store):
        enqueue_reflection([_result("600150", "建议卖出该股票")], store)
        assert len(store.all_pending()) == 1

    def test_持有不登记(self, store):
        n = enqueue_reflection([_result("600150", "投资建议：持有。")], store)
        assert n == 0
        assert store.all_pending() == []

    def test_失败的股票不登记(self, store):
        enqueue_reflection([_result("600150", "投资建议：买入。", status="failed")], store)
        assert store.all_pending() == []

    def test_超时的股票不登记(self, store):
        enqueue_reflection([_result("600150", "投资建议：买入。", status="timeout")], store)
        assert store.all_pending() == []

    def test_没有建议的不登记(self, store):
        enqueue_reflection([_result("600150", "")], store)
        assert store.all_pending() == []

    def test_混合结果只登记有方向的(self, store):
        results = [
            _result("600150", "投资建议：买入。"),
            _result("000001", "投资建议：持有。"),
            _result("000002", "建议卖出"),
            _result("000003", "投资建议：买入。", status="failed"),
        ]
        n = enqueue_reflection(results, store)
        assert n == 2
        codes = {r["stock_symbol"] for r in store.all_pending()}
        assert codes == {"600150", "000002"}

    def test_空列表返回零(self, store):
        assert enqueue_reflection([], store) == 0

    def test_传入分析日期(self, store):
        enqueue_reflection([_result("600150", "买入")], store, analysis_date="2026-10-14")
        assert store.all_pending()[0]["analysis_date"] == "2026-10-14"

    def test_单个失败不影响其他(self, store):
        class Bad:
            status = "completed"
            recommendation = "买入"

            @property
            def code(self):
                raise RuntimeError("炸了")

        results = [_result("600150", "买入"), Bad(), _result("000002", "卖出")]
        enqueue_reflection(results, store, analysis_date="2026-10-14")
        assert {r["stock_symbol"] for r in store.all_pending()} == {"600150", "000002"}


class TestSymbolSuffix:
    """入队的代码必须去掉交易所后缀。

    orchestrator 的 `Stock.code` 带 `.SH`/`.SZ`，但 `analysis_client._normalize_code()`
    提交分析时会把后缀去掉，所以 Mongo 里 `analysis_reports.stock_symbol` 和
    `stock_daily_quotes.symbol` **都是纯 6 位数字**（实测全库 1149 个代码 0 个带点）。

    实测 2026-10-23 入队的 8 条全带后缀（`600030.SH` 等）→ 永远匹配不到报告和行情，
    而 runner 把「找不到报告」当成「数据未到齐」不计失败，于是它们会**无声地永久滞留**。
    """

    def test_沪市后缀被去掉(self, store):
        enqueue_reflection([_result("600030.SH", "投资建议：买入。")], store,
                           analysis_date="2026-10-23")
        assert store.all_pending()[0]["stock_symbol"] == "600030"

    def test_深市后缀被去掉(self, store):
        enqueue_reflection([_result("001389.SZ", "投资建议：买入。")], store,
                           analysis_date="2026-10-23")
        assert store.all_pending()[0]["stock_symbol"] == "001389"

    def test_无后缀的保持不变(self, store):
        enqueue_reflection([_result("600030", "投资建议：买入。")], store,
                           analysis_date="2026-10-23")
        assert store.all_pending()[0]["stock_symbol"] == "600030"

    def test_去后缀后不会与已有条目重复(self, store):
        """回填登记的是无后缀的，流水线登记的是带后缀的 —— 必须合成一条。"""
        enqueue_reflection([_result("600030", "投资建议：买入。")], store,
                           analysis_date="2026-10-23")
        enqueue_reflection([_result("600030.SH", "投资建议：买入。")], store,
                           analysis_date="2026-10-23")
        assert len(store.all_pending()) == 1

    def test_空代码不入队(self, store):
        assert enqueue_reflection([_result("", "投资建议：买入。")], store,
                                  analysis_date="2026-10-23") == 0
        assert store.all_pending() == []

    def test_混合后缀的一批(self, store):
        results = [
            _result("600030.SH", "投资建议：买入。"),
            _result("601998.SH", "投资建议：买入。"),
            _result("001389.SZ", "建议卖出"),
            _result("601326", "投资建议：持有。"),
        ]
        assert enqueue_reflection(results, store, analysis_date="2026-10-23") == 3
        assert {r["stock_symbol"] for r in store.all_pending()} == \
            {"600030", "601998", "001389"}


class TestNormalizeSymbol:
    def test_各种写法(self):
        assert normalize_symbol("600030.SH") == "600030"
        assert normalize_symbol("001389.SZ") == "001389"
        assert normalize_symbol("600030") == "600030"
        assert normalize_symbol(" 600030.sh ") == "600030"

    def test_空值和None(self):
        assert normalize_symbol("") == ""
        assert normalize_symbol(None) == ""

    def test_与analysis_client的规则一致(self):
        """两边必须用同一条规则，否则队列和报告库对不上。"""
        sys.path.insert(0, "/home/lima/workspace/stock")
        from pipeline.analysis_client import TradingAgentsClient

        client = TradingAgentsClient.__new__(TradingAgentsClient)   # 不触发网络初始化
        for code in ("600030.SH", "001389.SZ", "600030"):
            assert normalize_symbol(code) == client._normalize_code(code)