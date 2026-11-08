"""Reflection worker：从历史行情反推决策收益，回填到记忆库。

分析当天拿不到自己的决策结果，所以本模块在 T+1 收盘后独立运行：
从 stock_daily_quotes 取后续收盘价，算出百分比收益，再交给
TradingAgents-CN 的 Reflector 写入 5 个记忆集合。
"""

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from pymongo import MongoClient

from pipeline.report_reader import extract_action

REFLECTABLE_ACTIONS = ("买入", "卖出")
MAX_FAILURES = 3

# 行情/报告的时间基准：行情日期是北京交易日，报告时间戳是 UTC（见 _to_beijing）
BEIJING_TZ = timezone(timedelta(hours=8))
MARKET_CLOSE_BJ = time(15, 0)


def should_reflect(action: Optional[str]) -> bool:
    """只有带方向的决策才有可学习的因果，「持有」不写入记忆。"""
    if not action:
        return False
    return action.strip() in REFLECTABLE_ACTIONS


def compute_realized_return(
    action: Optional[str], price_at_decision: Optional[float], price_after: Optional[float]
) -> Optional[float]:
    """算出带方向的收益率（小数，0.1 表示 10%）。

    买入看涨、卖出看跌，所以方向相反时取反。无法计算时返回 None。
    """
    if not should_reflect(action):
        return None
    if not price_at_decision or not price_after:
        return None
    if price_at_decision <= 0:
        return None
    change = (price_after - price_at_decision) / price_at_decision
    return change if action.strip() == "买入" else -change


class PendingReflectionStore:
    """待反思队列：分析当天只登记，T+1 收盘后由 worker 取走回填。"""

    def __init__(self, collection: str = "reflection_pending", db_name: str = "tradingagentscn"):
        self._coll = MongoClient("mongodb://localhost:27017")[db_name][collection]
        self._coll.create_index([("stock_symbol", 1), ("analysis_date", 1)], unique=True)

    def record(self, stock_symbol: str, analysis_date: str, action: str) -> bool:
        if not stock_symbol or not analysis_date or not should_reflect(action):
            return False
        self._coll.update_one(
            {"stock_symbol": stock_symbol, "analysis_date": analysis_date},
            {
                "$set": {
                    "stock_symbol": stock_symbol,
                    "analysis_date": analysis_date,
                    "action": action.strip(),
                },
                "$setOnInsert": {"fail_count": 0},
            },
            upsert=True,
        )
        return True

    def all_pending(self) -> list:
        return list(self._coll.find({"fail_count": {"$lt": MAX_FAILURES}}))

    def matured(self, stock_symbol: str, analysis_date: str, latest_date: str) -> bool:
        """分析日必须早于最新行情日，否则还没有「后续」可供判断对错。"""
        return bool(latest_date) and str(analysis_date) < str(latest_date)

    def mark_processed(self, stock_symbol: str, analysis_date: str) -> None:
        self._coll.delete_one({"stock_symbol": stock_symbol, "analysis_date": analysis_date})

    def mark_failed(self, stock_symbol: str, analysis_date: str, error: str) -> None:
        self._coll.update_one(
            {"stock_symbol": stock_symbol, "analysis_date": analysis_date},
            {"$inc": {"fail_count": 1}, "$set": {"last_error": str(error)[:200]}},
        )

    def clear(self) -> None:
        self._coll.delete_many({})

    def reset_failures(self) -> int:
        """把所有条目的失败计数归零，返回被归零的条数。

        fail_count 到 MAX_FAILURES 就永久不再重试（防毒丸数据），这是对的；
        但 embedding 服务抽风（手机 Vulkan 掉设备、SSH 隧道断）会让**整批**条目
        一起失败 —— 那不是条目的错。实测 2026-10-22 有 293 条卡在 fail_count=2，
        当晚再失败一次就会全部静默消失、记忆永久缺失。所以重跑前必须能清零。
        """
        res = self._coll.update_many({"fail_count": {"$gt": 0}}, {"$set": {"fail_count": 0}})
        return res.modified_count

    def enqueue(self, stock_symbol: str, analysis_date: str, action: str) -> bool:
        return self.record(stock_symbol, analysis_date, action)


def is_backfillable(doc: Dict, quotes_for_symbol: List[Dict]) -> bool:
    """这条历史决策现在能不能算出完整收益。

    回填时必须严格筛选：算不出结果的条目登记进去也只会永远空转。
    实测 1064 条买入/卖出里只有 503 条合格，其余是：
      · 分析日本身是周末/节假日（永不可能有行情）
      · 该股在行情库里根本没数据
      · 行情在分析日那天就断了（分析日就是该股最后一行）
    """
    if not doc:
        return False
    action = (doc.get("decision") or {}).get("action")
    if not should_reflect(action):
        return False
    symbol = doc.get("stock_symbol")
    analysis_date = doc.get("analysis_date")
    if not symbol or not analysis_date:
        return False
    price_at_decision, price_after = fetch_decision_prices(
        quotes_for_symbol, symbol, analysis_date, doc.get("timestamp")
    )
    return price_at_decision is not None and price_after is not None


def collect_backfillable(store, db=None, dry_run: bool = False) -> int:
    """把 Mongo 里现在就能算出结果的历史买卖决策补登记到队列。

    为什么不无脑全登记：算不出结果的条目（该股无行情、行情在分析日就断了）
    登记进去也只会每晚重试、永不出队。
    实测 1065 条买入/卖出里 598 条合格。

    返回新登记条数。dry_run 时只数不改队列。
    """
    if db is None:
        from pymongo import MongoClient

        db = MongoClient("mongodb://localhost:27017")["tradingagentscn"]

    reports = db["analysis_reports"]
    quotes_coll = db["stock_daily_quotes"]

    docs = list(
        reports.find(
            {"decision.action": {"$in": list(REFLECTABLE_ACTIONS)}},
            {"stock_symbol": 1, "analysis_date": 1, "decision": 1, "timestamp": 1},
        )
    )

    quotes_by_symbol: Dict[str, List[Dict]] = {}
    registered = 0
    for doc in docs:
        symbol = doc.get("stock_symbol")
        if not symbol:
            continue
        if symbol not in quotes_by_symbol:
            quotes_by_symbol[symbol] = list(
                quotes_coll.find({"symbol": symbol}, {"symbol": 1, "trade_date": 1, "close": 1})
            )
        if not is_backfillable(doc, quotes_by_symbol[symbol]):
            continue
        if dry_run:
            registered += 1
            continue
        if store.record(symbol, doc["analysis_date"], (doc.get("decision") or {}).get("action")):
            registered += 1
    return registered


class MongoReportSource:
    """按 (股票, 分析日) 取回当天的报告与结构化决策。

    分析当天写进 analysis_reports 的报告是不可变的，所以这里只读它，
    不去碰 eval_results 下那个「每只股只留最近一次」的 full_states_log.json。
    """

    def __init__(
        self,
        db_name: str = "tradingagentscn",
        uri: str = "mongodb://localhost:27017",
        tolerance_days: int = 3,
    ):
        from pymongo import MongoClient

        self._coll = MongoClient(uri)[db_name]["analysis_reports"]
        self._tolerance_days = tolerance_days

    def get(self, stock_symbol: str, analysis_date: str) -> Optional[Dict]:
        """找不到返回 None —— 那是「数据未到」，调用方不应记为失败。

        容忍 ±N 天：队列里的 analysis_date 是**流水线登记那一刻**的今天
        （`_enqueue_reflections` 用的是 `date.today()`），而报告里的
        analysis_date 是**该股分析完成那一刻**。跨午夜的批次两侧会错开一天
        （实测真有：某进程 22:39 起跑、跑到次日），精确匹配会让这些条目
        永远查不到报告、永远留在队列里空转。
        """
        projection = {"decision": 1, "reports": 1, "timestamp": 1}
        exact = self._coll.find_one(
            {"stock_symbol": stock_symbol, "analysis_date": analysis_date}, projection
        )
        if exact is not None:
            return exact

        lo, hi = _date_window(analysis_date, self._tolerance_days)
        if not lo:
            return None
        candidates = list(
            self._coll.find(
                {"stock_symbol": stock_symbol, "analysis_date": {"$gte": lo, "$lte": hi}},
                dict(projection, analysis_date=1),
            )
        )
        if not candidates:
            return None
        best = min(candidates, key=lambda d: _day_gap(d.get("analysis_date"), analysis_date))
        return {k: v for k, v in best.items() if k != "analysis_date"}


def _parse_iso_day(value):
    """把 "2026-10-14" / "20261014" / date / datetime 解析成 date，失败返回 None。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    digits = normalize_trade_date(value)
    if len(digits) < 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def _date_window(center: str, days: int):
    d = _parse_iso_day(center)
    if d is None:
        return None, None
    return (d - timedelta(days=days)).isoformat(), (d + timedelta(days=days)).isoformat()


def _day_gap(a, b) -> int:
    da, db = _parse_iso_day(a), _parse_iso_day(b)
    if da is None or db is None:
        return 10 ** 6
    return abs((da - db).days)


def normalize_symbol(code) -> str:
    """去掉交易所后缀，与 `analysis_reports.stock_symbol` / `stock_daily_quotes.symbol` 对齐。

    orchestrator 的 `Stock.code` 带 `.SH`/`.SZ`，但 `analysis_client._normalize_code()`
    提交分析时会去掉后缀，所以 Mongo 两边存的都是纯 6 位数字。
    实测 2026-10-23 入队的 8 条全带后缀 → 永远匹配不到报告和行情，
    而 runner 把「找不到报告」当「数据未到齐」不计失败，于是无声地永久滞留。
    """
    return str(code or "").split(".")[0].strip()


def normalize_trade_date(value: Optional[str]) -> str:
    """把 "2026-10-14"、"2026-10-14 18:31:02" 统一成 "20261014"。"""
    if not value:
        return ""
    digits = "".join(ch for ch in str(value)[:10] if ch.isdigit())
    return digits


def latest_market_date(quotes: List[Dict]) -> str:
    dates = [normalize_trade_date(q.get("trade_date")) for q in quotes]
    return max(dates) if dates else ""


def _to_beijing(timestamp) -> Optional[datetime]:
    """把报告时间戳换算成北京时间。

    **踩过的坑**：`analysis_reports.timestamp` 是 UTC。app 用 `utcnow()` 落库，
    而 Mongo 的 BSON date 本身就是 UTC，所以读出来是 naive UTC，直接取 `.hour`
    会整整差 8 小时 —— 北京时间傍晚 19:00 完成的分析会被当成「盘前」。
    行情日期（`stock_daily_quotes.trade_date`）却是北京交易日，两边不对齐。
    """
    if timestamp is None:
        return None
    if isinstance(timestamp, datetime):
        dt = timestamp
    else:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", str(timestamp))
        if not m:
            return None
        y, mo, d, hh, mm = (int(x) for x in m.groups())
        dt = datetime(y, mo, d, hh, mm)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ)


def decision_cutoff(analysis_date: str, timestamp=None) -> str:
    """「决策当时 agent 能看到的价格」截止到哪天（紧凑 YYYYMMDD）。

    报告里的 `analysis_date` 只是**完成时刻**的日期（而且是 UTC 日期），
    它既可能落在周末/节假日（那天永远没有行情），也可能在北京时间盘前
    （当天还没收盘，agent 看到的是上一个交易日）。所以要用时刻补回「几点」。

    取不到时间戳时退回「截止到分析日当天」—— 这是保守选择，与既往行为一致。
    """
    local = _to_beijing(timestamp)
    if local is None:
        day = _parse_iso_day(analysis_date)
        return day.strftime("%Y%m%d") if day else ""
    cutoff = local.date() if local.time() >= MARKET_CLOSE_BJ else local.date() - timedelta(days=1)
    return cutoff.strftime("%Y%m%d")


def fetch_decision_prices(
    quotes: List[Dict],
    stock_symbol: str,
    analysis_date: str,
    timestamp=None,
) -> Tuple[Optional[float], Optional[float]]:
    """取「决策时 agent 看到的价位」与「其后第一个可交易的收盘价」（跳过停牌）。

    为什么不是「必须精确命中分析日当天」：报告里的 analysis_date 是分析**完成
    时刻**的日期，它会落在周末/节假日（那天永远没有行情），也可能在交易日盘前
    （当天还没收盘，agent 看到的是上一个交易日）。精确匹配会让前者永远算不出
    结果、让后者基准价偏晚一整天。

    实测 1065 条买入/卖出里：上百条靠这两条修正才救得回来 / 才不至于算错。
    """
    cutoff = decision_cutoff(analysis_date, timestamp)
    if not cutoff:
        return None, None
    rows = sorted(
        (
            (normalize_trade_date(q.get("trade_date")), q.get("close"))
            for q in quotes
            if q.get("symbol") == stock_symbol and q.get("close")
        ),
        key=lambda r: r[0],
    )
    before = [r for r in rows if r[0] <= cutoff]
    if not before:
        return None, None
    after = [r for r in rows if r[0] > cutoff]
    return float(before[-1][1]), (float(after[0][1]) if after else None)


def enqueue_reflection(
    results: Iterable, store: PendingReflectionStore, analysis_date: Optional[str] = None
) -> int:
    """把本轮分析里带方向的决策登记进待反思队列，返回登记条数。

    单只股票出错不应中断整批登记，因此逐条捕获异常。
    """
    if not analysis_date:
        analysis_date = date.today().isoformat()
    queued = 0
    for result in results:
        try:
            if getattr(result, "status", "") != "completed":
                continue
            action = extract_action({"recommendation": getattr(result, "recommendation", "")})
            symbol = normalize_symbol(getattr(result, "code", ""))
            if not symbol:
                continue
            if store.record(symbol, analysis_date, action):
                queued += 1
        except Exception:
            continue
    return queued