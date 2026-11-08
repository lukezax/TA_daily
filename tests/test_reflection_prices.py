"""行情取价逻辑测试。

日期/时区是最容易出错的地方，这里踩过两个坑：

1. `analysis_date` 来自报告是 "2026-10-14"，而 `stock_daily_quotes.trade_date`
   存的是 "20261014"。
2. **`analysis_reports.timestamp` 是 UTC**（app 用 `utcnow()` 落库），而行情日期
   是**北京**交易日。直接拿 UTC 的 `.hour` 比 15:00 会整整差 8 小时 ——
   北京时间傍晚 19:00 完成的分析会被误判成「盘前」，基准价白白退后一天。

取价口径要解决三个真实问题（都由「报告里的 analysis_date 是分析**完成时刻**
的日期」引起，实测 1065 条买入/卖出里数百条受影响）：

1. 完成时刻可能落在**周末/节假日**，那天永远没有行情 → 必须退到「之前最近的收盘」。
2. 完成时刻可能在交易日**盘前**（北京时间凌晨）→ agent 看不到当天收盘，
   基准价只能取上一个已收盘交易日。
3. 时区不换算 → 北京时间收盘后完成的会被误判成盘前（见上）。
"""
import sys
from datetime import datetime

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.reflection_worker import (
    decision_cutoff,
    fetch_decision_prices,
    latest_market_date,
    normalize_trade_date,
)


@pytest.fixture
def fake_quotes():
    """模拟 stock_daily_quotes 文档，600151 在 10-15 停牌用于测跳空。"""
    return [
        {"symbol": "600150", "trade_date": "20261013", "close": 98.0},
        {"symbol": "600150", "trade_date": "20261014", "close": 100.0},
        {"symbol": "600150", "trade_date": "20261015", "close": 105.0},
        {"symbol": "600150", "trade_date": "20261016", "close": 110.0},
        {"symbol": "600151", "trade_date": "20261014", "close": 50.0},
        {"symbol": "600151", "trade_date": "20261016", "close": 52.0},
    ]


@pytest.fixture
def weekend_quotes():
    """10-16 周五、10-19 周一，中间 10-17/18 是周末。"""
    return [
        {"symbol": "600150", "trade_date": "20261016", "close": 110.0},
        {"symbol": "600150", "trade_date": "20261019", "close": 114.0},
    ]


class TestNormalizeTradeDate:
    def test_带横线转紧凑(self):
        assert normalize_trade_date("2026-10-14") == "20261014"

    def test_已是紧凑格式保持不变(self):
        assert normalize_trade_date("20261014") == "20261014"

    def test_带时间的取日期部分(self):
        assert normalize_trade_date("2026-10-14 18:31:02") == "20261014"

    def test_空值返回空(self):
        assert normalize_trade_date("") == ""
        assert normalize_trade_date(None) == ""


class TestLatestMarketDate:
    def test_返回最新交易日的紧凑格式(self, fake_quotes):
        assert latest_market_date(fake_quotes) == "20261016"

    def test_空集合返回空(self, fake_quotes):
        assert latest_market_date([]) == ""


class TestDecisionCutoff:
    """「决策时 agent 能看到的价格」截止到哪天。

    时间戳按 **UTC** 给（与 Mongo 里存的一致），注释里标出对应的北京时间。
    """

    def test_北京时间盘前完成退一天(self):
        # UTC 06:30 → 北京 14:30（当天还没收盘）
        assert decision_cutoff("2026-10-15", "2026-10-15 06:30:00") == "20261014"

    def test_北京时间凌晨完成退一天(self):
        # UTC 00:25 → 北京 08:25
        assert decision_cutoff("2026-05-13", "2026-05-13 00:25:57Z") == "20260512"

    def test_北京时间收盘后完成取当天(self):
        # UTC 07:30 → 北京 15:30
        assert decision_cutoff("2026-10-15", "2026-10-15 07:30:00") == "20261015"

    def test_北京时间恰好收盘取当天(self):
        # UTC 07:00 → 北京 15:00
        assert decision_cutoff("2026-10-15", "2026-10-15 07:00:00") == "20261015"

    def test_北京时间傍晚完成取当天_时区回归(self):
        """关键回归：UTC 11:04 = 北京 19:04，是收盘**后**。

        曾经直接拿 UTC 的 hour(=11) 比 15 → 误判成盘前 → 基准价少算一天。
        """
        assert decision_cutoff("2026-10-15", "2026-10-15 11:04:00") == "20261015"

    def test_UTC晚间完成跨到北京次日凌晨(self):
        """UTC 16:43 = 北京次日 00:43 —— 北京那边市场还没开，退到北京前一日。"""
        assert decision_cutoff("2026-10-18", "2026-10-18 16:43:04Z") == "20261018"

    def test_周末完成时退不退都一样(self):
        """10-18 是周日，当天本来就没有行情，怎么算都落在前一个交易日。"""
        # UTC 02:00 → 北京 10-18 10:00（周末盘前）
        assert decision_cutoff("2026-10-18", "2026-10-18 02:00:00") == "20261017"
        # UTC 07:49 → 北京 10-18 15:49（周末盘后）
        assert decision_cutoff("2026-10-18", "2026-10-18 07:49:00") == "20261018"

    def test_缺时间戳时退回分析日当天(self):
        """保守选择，与既往行为一致。"""
        assert decision_cutoff("2026-10-15", None) == "20261015"

    def test_datetime对象也能判(self):
        assert decision_cutoff("2026-10-15", datetime(2026, 10, 15, 11, 4)) == "20261015"

    def test_时间戳不可解析时退回分析日(self):
        assert decision_cutoff("2026-10-15", "坏时间戳") == "20261015"

    def test_都不合法时返回空(self):
        assert decision_cutoff("坏日期", "坏时间戳") == ""


class TestFetchDecisionPrices:
    def test_取分析日与下一交易日的收盘价(self, fake_quotes):
        p0, p1 = fetch_decision_prices(fake_quotes, "600150", "2026-10-14")
        assert p0 == 100.0
        assert p1 == 105.0

    def test_日期带横线也能取到(self, fake_quotes):
        p0, p1 = fetch_decision_prices(fake_quotes, "600150", "2026-10-14")
        assert p0 is not None

    def test_分析日是最后一天则没有后续价(self, fake_quotes):
        p0, p1 = fetch_decision_prices(fake_quotes, "600150", "2026-10-16")
        assert p0 == 110.0
        assert p1 is None

    def test_不存在的股票返回None(self, fake_quotes):
        p0, p1 = fetch_decision_prices(fake_quotes, "999999", "2026-10-14")
        assert p0 is None and p1 is None

    def test_跳过停牌日取下一个真实交易日(self, fake_quotes):
        """10-15 停牌，10-16 才是下一个交易日"""
        p0, p1 = fetch_decision_prices(fake_quotes, "600151", "2026-10-14")
        assert p0 == 50.0
        assert p1 == 52.0

    # ── 问题 1：完成时刻落在周末/节假日 ──

    def test_分析日落在周末时取之前最近的收盘(self, weekend_quotes):
        """10-17 是周六，那天永远没有行情。agent 决策时看到的是周五收盘。"""
        p0, p1 = fetch_decision_prices(weekend_quotes, "600150", "2026-10-17")
        assert p0 == 110.0
        assert p1 == 114.0

    def test_分析日停牌时也退到之前最近的收盘(self, fake_quotes):
        """10-15 该股停牌，没有收盘价可用。"""
        p0, p1 = fetch_decision_prices(fake_quotes, "600151", "2026-10-15")
        assert p0 == 50.0   # 10-14 的收盘
        assert p1 == 52.0   # 10-16 的收盘

    def test_所有行情都在分析日之后时没有基准价(self, weekend_quotes):
        p0, p1 = fetch_decision_prices(weekend_quotes, "600150", "2026-10-08")
        assert p0 is None and p1 is None

    def test_分析日晚于所有行情时只剩基准价(self, fake_quotes):
        p0, p1 = fetch_decision_prices(fake_quotes, "600150", "2099-01-01")
        assert p0 == 110.0
        assert p1 is None   # 没有「之后」，算不出收益

    # ── 问题 2/3：完成时刻在盘前（含时区换算） ──

    def test_北京盘前完成时基准价取前一交易日(self, fake_quotes):
        """北京 10-15 14:00 完成：agent 看不到 10-15 的收盘（还没发生）。"""
        p0, p1 = fetch_decision_prices(
            fake_quotes, "600150", "2026-10-15", "2026-10-15 06:00:00"
        )
        assert p0 == 100.0   # 10-14 的收盘
        assert p1 == 105.0   # 10-15 的收盘（决策后可交易的第一天）

    def test_北京收盘后完成时基准价取当天(self, fake_quotes):
        p0, p1 = fetch_decision_prices(
            fake_quotes, "600150", "2026-10-15", "2026-10-15 07:30:00"
        )
        assert p0 == 105.0
        assert p1 == 110.0

    def test_北京傍晚完成时基准价取当天_时区回归(self, fake_quotes):
        """UTC 11:04 = 北京 19:04 收盘后。误用时区会错误地退到 10-14。"""
        p0, p1 = fetch_decision_prices(
            fake_quotes, "600150", "2026-10-15", "2026-10-15 11:04:00"
        )
        assert p0 == 105.0
        assert p1 == 110.0

    def test_北京凌晨完成遇上周一取上周五(self, weekend_quotes):
        """UTC 10-18 18:00 → 北京 10-19 02:00（周一凌晨）。"""
        p0, p1 = fetch_decision_prices(
            weekend_quotes, "600150", "2026-10-18", "2026-10-18 18:00:00"
        )
        assert p0 == 110.0   # 周五
        assert p1 == 114.0   # 周一

    def test_盘前完成且前面没有行情时返回None(self, weekend_quotes):
        p0, p1 = fetch_decision_prices(
            weekend_quotes, "600150", "2026-10-16", "2026-10-16 00:30:00"
        )
        assert p0 is None and p1 is None

    def test_不传时间戳时退回分析日当天(self, fake_quotes):
        assert fetch_decision_prices(fake_quotes, "600150", "2026-10-15") == \
            fetch_decision_prices(
                fake_quotes, "600150", "2026-10-15", "2026-10-15 11:04:00"
            )
