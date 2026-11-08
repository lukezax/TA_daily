"""反思 worker 每日收盘后回填决策收益的主循环。

与旧版的区别：不再调 `graph.reflect_and_remember`（那要 5 次 LLM），
而是把报告装配成确定性文本后交给 `MemoryWriter`（1 次 embedding）。
所以这里既不需要 TradingAgentsGraph，也不需要 LLM 客户端。
"""
import logging

from typing import Callable, Optional

from pipeline.reflection_text import (
    ROLE_FIELDS,
    build_recommendation,
    build_situation,
    compute_raw_change,
    extract_role_text,
)
from pipeline.reflection_worker import (
    MongoReportSource,
    PendingReflectionStore,
    compute_realized_return,
    decision_cutoff,
    fetch_decision_prices,
    latest_market_date,
    normalize_trade_date,
    should_reflect,
)
from pipeline.report_reader import extract_action

logger = logging.getLogger(__name__)


class ReflectionRunner:
    """扫描待反思队列，算出收益后写入 5 个记忆集合。"""

    def __init__(
        self,
        store: Optional[PendingReflectionStore] = None,
        quotes_provider: Optional[Callable[[], list]] = None,
        writer: Optional[Callable[[], object]] = None,
        report_source: Optional[object] = None,
        dry_run: bool = False,
    ):
        self.store = store or PendingReflectionStore()
        self._quotes = quotes_provider
        self._writer = writer
        self._reports = report_source if report_source is not None else MongoReportSource()
        self.dry_run = dry_run

    def _load_quotes(self, symbols, since) -> list:
        """只取队列里需要的股票、以及不早于最早分析日的行情。

        不做过滤会把 150 万行（约 1GB）整个读进内存 ——
        本机可用内存只有十几 GB，还要和 27B 模型、在跑的分析进程一起分。
        """
        if self._quotes is not None:
            return self._quotes()
        if not symbols:
            return []

        from pymongo import MongoClient

        query = {"symbol": {"$in": sorted(symbols)}}
        if since:
            # 算收益只需要「分析日当行 + 其后一行」，更早的行情没用
            query["trade_date"] = {"$gte": since}
        coll = MongoClient("mongodb://localhost:27017")["tradingagentscn"]["stock_daily_quotes"]
        return list(coll.find(query, {"symbol": 1, "trade_date": 1, "close": 1}))

    def _resolve_writer(self):
        """writer 可以是工厂（每次运行建一次），也可以是现成对象。"""
        if self._writer is None:
            raise RuntimeError("writer 未配置，无法写入记忆")
        return self._writer() if callable(self._writer) else self._writer

    def _drop(self, symbol: str, analysis_date: str):
        """把一条「无需再处理」的项移出队列。试运行时只记日志，不动队列。"""
        if self.dry_run:
            logger.info("[试运行] %s %s 无需处理，真实执行时会出队", symbol, analysis_date)
            return
        self.store.mark_processed(symbol, analysis_date)

    def run_once(self) -> int:
        """处理一轮，返回成功条数。任何单只失败都不影响其他。"""
        pending = self.store.all_pending()
        if not pending:
            return 0

        symbols = {item["stock_symbol"] for item in pending}
        since = min((normalize_trade_date(item["analysis_date"]) for item in pending), default="")
        try:
            quotes = self._load_quotes(symbols, since)
        except Exception as e:
            logger.warning("拉取行情失败，本轮跳过: %s", e)
            return 0

        latest = latest_market_date(quotes)
        # 惰性构造：空队列的夜里不必去连 ChromaDB
        writer = None

        done = 0
        for item in pending:
            symbol = item["stock_symbol"]
            analysis_date = item["analysis_date"]
            if not self.store.matured(symbol, analysis_date, latest):
                continue

            doc = self._reports.get(symbol, analysis_date)
            if doc is None:
                # 报告还没落库属于「数据未到齐」，下轮自然能取到，不计失败
                logger.info("⏳ %s %s 报告未到齐，跳过本轮", symbol, analysis_date)
                continue

            # 队列里的 action 是从文本正则抽的，可能不准 —— 以 Mongo 的结构化字段为准。
            # 实测确实会不一致（队列 买入 / Mongo 持有）。
            reports = doc.get("reports") or {}
            action = extract_action(doc) or item.get("action")
            if not should_reflect(action):
                # 用户只要记买卖。持有必须出队，不能留着空转 ——
                # compute_realized_return('持有', ...) 恒为 None，它永远等不到收益。
                logger.info("⏭️ %s %s 权威动作是「%s」，不入记忆，出队",
                            symbol, analysis_date, action or "空")
                self._drop(symbol, analysis_date)
                continue

            p0, p1 = fetch_decision_prices(
                quotes, symbol, analysis_date, doc.get("timestamp")
            )
            pct = compute_realized_return(action, p0, p1)
            if pct is None:
                # 行情同步有滞后，T+1 价格到齐后下轮自然可算，不计失败
                logger.info("⏳ %s %s 行情未到齐，跳过本轮", symbol, analysis_date)
                continue

            if self.dry_run:
                logger.info("[试运行] %s %s %s 收益 %+.2f%%", symbol, analysis_date, action, pct * 100)
                done += 1
                continue

            if writer is None:
                # 放在 try 之外：写入器建不起来是配置/环境错误，
                # 该整轮中断（条目原样留在队列，下轮再试），
                # 而不是记成条目失败 —— 那样 3 次后会被静默丢弃。
                writer = self._resolve_writer()

            try:
                situation = build_situation(reports)
                if writer.already_written(situation):
                    # 回填会把所有算得出结果的决策重新登记（含早就写好的），
                    # 而成功的条目已出队 —— 不拦住就会重新 embedding 并写成重复条目。
                    logger.info("⏭️ %s %s 已在记忆库里，出队（不重复 embedding）",
                                symbol, analysis_date)
                    self._drop(symbol, analysis_date)
                    done += 1
                    continue
                raw = compute_raw_change(p0, p1)
                recommendations = {
                    role: build_recommendation(
                        role=role,
                        analysis_date=analysis_date,
                        action=action,
                        raw=raw,
                        pct=pct,
                        role_text=extract_role_text(reports, field),
                    )
                    for role, field in ROLE_FIELDS.items()
                }
                written = writer.write_all(situation, recommendations)
                self.store.mark_processed(symbol, analysis_date)
                done += 1
                logger.info("✅ %s %s 收益 %+.2f%% 已写入 %d 个记忆集合",
                            symbol, analysis_date, pct * 100, written)
            except Exception as e:
                self.store.mark_failed(symbol, analysis_date, str(e))
                logger.warning("❌ %s %s 记忆写入失败: %s", symbol, analysis_date, e)
        return done
