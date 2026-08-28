"""
流水线编排器
协调整个流水线的执行流程：筛选 → 分析 → 报告
"""

import logging
from typing import Dict

from pipeline.config import PipelineConfig
from pipeline.filter_runner import StockFilterRunner
from pipeline.analysis_client import TradingAgentsClient
from pipeline.report_generator import ReportGenerator
from pipeline.models import PipelineResult, StockAnalysisResult

logger = logging.getLogger(__name__)


def _is_date_trading_day(d) -> bool:
    """判断指定日期是否为 A 股交易日（周一~周五且非法定节假日；周六周日即使调休补班也不开市）"""
    if d.weekday() >= 5:
        return False
    try:
        from chinese_calendar import is_holiday
        return not is_holiday(d)
    except ImportError:
        # chinese_calendar 未安装时降级：仅排除周末
        return True


def next_trading_day(now=None):
    """计算下一个交易日（报告日期）。

    分界线 09:30（开盘）：
    - 09:30 之前 → 今天（尚未开盘）
    - 09:30 之后 → 之后的第一个交易日

    注意：deadline（报告日当天 09:00）必须由本函数结果推导，
    不可单独用 today()+1 计算——否则过零点手动启动等场景下
    报告日与截止日会分叉（如 00:03 启动：报告日=今天，截止日却=后天）。
    """
    from datetime import date, datetime, timedelta

    now = now or datetime.now()
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    today = now.date()
    candidate = today if now < market_open else today + timedelta(days=1)

    for _ in range(10):
        if _is_date_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    return candidate


class PipelineOrchestrator:
    """流水线编排器"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.filter_runner = StockFilterRunner(config)
        self.analysis_client = TradingAgentsClient(config)
        self.report_generator = ReportGenerator(config)

    def run(self, target_date=None, deadline=None, debug=False, deep_mode=False, lite_mode=False) -> PipelineResult:
        """
        执行完整流水线：筛选 → 分析 → 报告

        Args:
            target_date: 目标交易日（date 对象）。如果为 None，自动计算下一个交易日。
            deadline: 截止时间（datetime 对象）。超过此时间后不再提交新批次，
                      但正在执行的批次会跑完。None 表示无限制（手动任务）。
            debug: 调试模式。跳过数据更新（市值快筛+API拉取），只用本地缓存跑流程。

        Fallback 机制：
        - Stock_Filter 失败 → 致命错误，退出
        - TradingAgents 不可用 → 跳过分析，仅用筛选数据生成报告
        - 单只股票分析失败 → 标记为失败，继续其他
        - 所有分析失败 → 仍生成报告（仅含筛选数据）

        增量报告：
        - 筛选完成后立即生成初始报告（仅含筛选数据）
        - 每批分析完成后重新生成报告（逐步丰富）
        - 失败任务重试后再次更新报告
        """
        logger.info("流水线开始执行")

        # 确定报告日期（目标交易日）
        if target_date is None:
            # 手动执行时自动计算（9:30 前算今天，9:30 后算下一个交易日）
            target_date = next_trading_day()

        report_date = target_date.strftime('%Y-%m-%d')
        logger.info("报告日期（目标交易日）: %s", report_date)

        # ── Step 1: 执行筛选 ──
        logger.info("开始执行 Stock_Filter 筛选")
        try:
            filter_results = self.filter_runner.execute(debug=debug)
        except Exception as e:
            logger.error("Stock_Filter 执行失败（致命错误）: %s", e, exc_info=True)
            raise RuntimeError(f"Stock_Filter 执行失败: {e}") from e

        # 覆盖报告日期为目标交易日（而非 date.today()）
        filter_results.date = report_date

        # 筛选返回空结果且 total_scanned=0 → 致命错误
        if filter_results.total_scanned == 0 and not filter_results.stocks:
            logger.error("Stock_Filter 返回空结果（total_scanned=0），视为致命错误")
            raise RuntimeError("Stock_Filter 返回空结果（total_scanned=0）")

        # ── Step 1.5: 缠论高分扫描（全市场缠论高分通道，独立分类）──
        logger.info("开始执行缠论高分扫描（全市场缠论脚本，非 LLM）")
        try:
            from pipeline.czsc_scanner import scan_high_score, CZSC_HIGH_SCORE_TAG

            czsc_high_stocks, czsc_pool_size = scan_high_score()
            if czsc_high_stocks:
                existing_codes = {s.code for s in filter_results.stocks}
                added = 0
                for cs in czsc_high_stocks:
                    if cs.code in existing_codes:
                        # 已有 B1/B2 记录 → 追加"缠高分"标签与缠论详情
                        for s in filter_results.stocks:
                            if s.code == cs.code:
                                if CZSC_HIGH_SCORE_TAG not in s.tags:
                                    s.tags.append(CZSC_HIGH_SCORE_TAG)
                                s.details.update(cs.details)
                    else:
                        filter_results.stocks.append(cs)
                        added += 1
                logger.info(
                    "缠高分扫描: 新增 %d 只，合并标签 %d 只，共 %d 只",
                    added,
                    len(czsc_high_stocks) - added,
                    len(czsc_high_stocks),
                )
            # 扫描池大小并入总扫描数（去重统计：两通道扫描池相同则取较大值）
            filter_results.total_scanned = max(
                filter_results.total_scanned, czsc_pool_size
            )
        except Exception as e:
            logger.error("缠论高分扫描失败（降级跳过，不影响主流程）: %s", e, exc_info=True)

        logger.info(
            "筛选完成: 扫描 %d 只，通过 %d 只",
            filter_results.total_scanned,
            filter_results.total_passed,
        )

        # 筛选通过数为 0 → 生成空报告
        if filter_results.total_passed == 0:
            logger.info("无股票通过筛选，生成空报告")
            report_path = self.report_generator.generate_empty_report(filter_results.date)
            self.report_generator.generate_index()
            return PipelineResult(
                date=filter_results.date,
                total_scanned=filter_results.total_scanned,
                total_filtered=0,
                analysis_completed=0,
                analysis_failed=0,
                report_path=str(report_path),
                success=True,
            )

        # ── Step 2: 生成初始报告（仅含筛选数据，无 AI 分析）──
        logger.info("生成初始报告（仅筛选数据）")
        try:
            report_path = self.report_generator.generate(
                date=filter_results.date,
                filter_data=filter_results,
                analysis_data={},
            )
            self.report_generator.generate_index()
        except Exception as e:
            logger.error("初始报告生成失败: %s", e, exc_info=True)

        # ── Step 3: 尝试 AI 分析（逐批处理，增量更新报告）──
        analysis_results: Dict[str, StockAnalysisResult] = {}

        if not self.analysis_client.is_available():
            logger.warning("TradingAgents 服务不可用，跳过 AI 分析")
        else:
            # ── Step 2.5: 数据预热（确保分析时能从 MongoDB 拿到数据）──
            try:
                from pipeline.data_preheater import DataPreheater
                preheater = DataPreheater()
                logger.info("开始数据预热（K线 → MongoDB）...")
                preheater.preheat(filter_results.stocks)
                logger.info("开始指标预热（MACD/KDJ/BOLL → MongoDB）...")
                preheater.preheat_indicators(filter_results.stocks)
            except Exception as e:
                logger.warning(f"数据预热异常（不影响分析流程）: {e}")

            logger.info(
                "开始 AI 分析: %d 只股票", len(filter_results.stocks)
            )
            try:
                # 登录一次，获取 token
                token = self.analysis_client.login()
                if not token:
                    logger.error("无法登录 TradingAgents，跳过 AI 分析")
                else:
                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    }
                    # 分批处理
                    batch_size = self.config.batch_size
                    stocks = filter_results.stocks
                    batches = [
                        stocks[i : i + batch_size]
                        for i in range(0, len(stocks), batch_size)
                    ]

                    for batch_idx, batch in enumerate(batches, 1):
                        # 检查是否超过截止时间（自动任务限制）
                        if deadline is not None:
                            from datetime import datetime
                            if datetime.now() >= deadline:
                                logger.info(
                                    "已到达截止时间 %s，跳过剩余 %d 个批次",
                                    deadline.strftime("%H:%M"),
                                    len(batches) - batch_idx + 1,
                                )
                                break

                        logger.info(
                            "提交批次 %d/%d（%d 只股票）",
                            batch_idx, len(batches), len(batch),
                        )
                        batch_results = self.analysis_client.process_single_batch(
                            batch, headers, self.config.timeout_per_stock,
                            analysis_date=filter_results.date,
                            deadline=deadline,
                            deep_mode=deep_mode,
                            lite_mode=lite_mode,
                        )
                        analysis_results.update(batch_results)

                        # 每批完成后增量更新报告
                        try:
                            report_path = self.report_generator.generate(
                                date=filter_results.date,
                                filter_data=filter_results,
                                analysis_data=analysis_results,
                            )
                            logger.info("批次 %d 完成，报告已更新", batch_idx)
                        except Exception as e:
                            logger.warning("批次 %d 报告更新失败: %s", batch_idx, e)

                    # ── Step 4: 重试失败任务 ──
                    failed_stocks = [
                        stock for stock in filter_results.stocks
                        if analysis_results.get(stock.code)
                        and analysis_results[stock.code].status in ("failed", "timeout")
                    ]

                    # 检查是否超过截止时间（自动任务限制）
                    if deadline is not None:
                        from datetime import datetime
                        if datetime.now() >= deadline:
                            logger.info(
                                "已到达截止时间 %s，跳过重试",
                                deadline.strftime("%H:%M"),
                            )
                            failed_stocks = []

                    if failed_stocks:
                        logger.info(
                            "重试 %d 只失败/超时的股票", len(failed_stocks)
                        )
                        retry_results = self.analysis_client.process_single_batch(
                            failed_stocks, headers, self.config.timeout_per_stock,
                            analysis_date=filter_results.date,
                            deadline=deadline,
                            deep_mode=deep_mode,
                            lite_mode=lite_mode,
                        )
                        # 仅更新重试成功的结果
                        for code, result in retry_results.items():
                            if result.status == "completed":
                                analysis_results[code] = result
                                logger.info("股票 %s 重试成功", code)

                        # 重试后再次更新报告
                        try:
                            report_path = self.report_generator.generate(
                                date=filter_results.date,
                                filter_data=filter_results,
                                analysis_data=analysis_results,
                            )
                            logger.info("重试完成，报告已更新")
                        except Exception as e:
                            logger.warning("重试后报告更新失败: %s", e)

            except Exception as e:
                logger.error("AI 分析过程异常: %s", e, exc_info=True)
                # 分析异常不是致命错误，继续生成报告

        # 统计分析结果
        analysis_completed = sum(
            1 for r in analysis_results.values() if r.status == "completed"
        )
        analysis_failed = sum(
            1 for r in analysis_results.values() if r.status in ("failed", "timeout")
        )

        if analysis_results:
            logger.info(
                "AI 分析结果: 完成 %d, 失败 %d",
                analysis_completed,
                analysis_failed,
            )

        # ── Step 5: 生成最终报告 ──
        logger.info("生成最终报告")
        try:
            report_path = self.report_generator.generate(
                date=filter_results.date,
                filter_data=filter_results,
                analysis_data=analysis_results,
            )
            self.report_generator.generate_index()
            logger.info("报告已生成: %s", report_path)
        except Exception as e:
            logger.error("报告生成失败: %s", e, exc_info=True)
            return PipelineResult(
                date=filter_results.date,
                total_scanned=filter_results.total_scanned,
                total_filtered=filter_results.total_passed,
                analysis_completed=analysis_completed,
                analysis_failed=analysis_failed,
                report_path="",
                success=False,
                error_message=f"报告生成失败: {e}",
            )

        logger.info("流水线执行完成")
        return PipelineResult(
            date=filter_results.date,
            total_scanned=filter_results.total_scanned,
            total_filtered=filter_results.total_passed,
            analysis_completed=analysis_completed,
            analysis_failed=analysis_failed,
            report_path=str(report_path),
            success=True,
        )


class PipelineScheduler:
    """定时调度器，每交易日执行流水线"""

    def __init__(self, config: PipelineConfig, deep_mode: bool = False, lite_mode: bool = False):
        self.config = config
        self.deep_mode = deep_mode
        self.lite_mode = lite_mode
        self.orchestrator = PipelineOrchestrator(config)

    def start(self):
        """启动定时调度，每天在配置时间触发，内部判断是否为交易日"""
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger

        self.scheduler = BlockingScheduler()

        # Parse schedule_time from config (format: "HH:MM")
        hour, minute = self.config.schedule_time.split(":")

        # 每天都触发（包括周末），由 _run_pipeline 内部判断是否为交易日
        trigger = CronTrigger(
            hour=int(hour),
            minute=int(minute),
        )

        self.scheduler.add_job(self._run_pipeline, trigger, id="daily_pipeline", misfire_grace_time=60)
        logger.info("定时调度已启动: 每天 %s 触发（自动跳过非交易日）", self.config.schedule_time)

        # 策略研究员：每天 10:00 触发
        researcher_trigger = CronTrigger(hour=10, minute=0)
        self.scheduler.add_job(self._run_researcher, researcher_trigger,
                               id="strategy_researcher", misfire_grace_time=60)
        logger.info("策略研究员调度已启动: 每天 10:00 触发（自动跳过非交易日）")

        self.scheduler.start()

    def _is_trading_day(self) -> bool:
        """
        判断当前触发时间对应的目标日期是否为 A 股交易日。

        A 股交易日规则：
        - 周一到周五 且 不是法定节假日 → 交易日
        - 周六周日 → 不开市（即使调休补班也不开）
        - 法定节假日 → 不开市
        """
        target = self._get_next_trading_day()
        # 如果能算出下一个交易日，说明当前应该执行
        # _get_next_trading_day 内部已经做了交易日判断
        return target is not None

    def _get_next_trading_day(self):
        """
        计算下一个交易日（报告日期），规则见 next_trading_day()。
        """
        return next_trading_day()

    def _is_date_trading_day(self, d) -> bool:
        """判断指定日期是否为交易日"""
        return _is_date_trading_day(d)

    def _get_target_date(self):
        """根据触发时间确定目标交易日（兼容旧调用）"""
        return self._get_next_trading_day()

    def _run_pipeline(self):
        """
        调度触发时判断是否应该执行。

        规则：只在"明天是交易日"时执行。
        - 周一~周四晚 → 明天是交易日 → 执行
        - 周五晚 → 明天是周六（非交易日）→ 跳过
        - 周六/周日 → 明天不是交易日 → 跳过（周日晚除外）
        - 周日晚 → 明天是周一（交易日）→ 执行
        - 节假日前一天晚 → 明天是节假日 → 跳过
        - 节假日最后一天晚 → 明天恢复交易 → 执行

        自动任务截止时间：次日早上 9:00。超过后不再提交新批次，
        正在执行的批次会跑完。
        """
        from datetime import date, timedelta, datetime

        tomorrow = date.today() + timedelta(days=1)

        if not self._is_date_trading_day(tomorrow):
            logger.info("明天 %s 不是交易日，跳过执行", tomorrow)
            return

        # 明天是交易日 → 报告日期就是明天
        target = tomorrow

        # 计算截止时间：明天早上 9:00
        deadline = datetime.combine(tomorrow, datetime.min.time()).replace(hour=9, minute=0, second=0)

        logger.info("=" * 60)
        logger.info("定时任务触发，目标交易日: %s，截止时间: %s，开始执行流水线", target, deadline.strftime("%Y-%m-%d %H:%M"))
        try:
            result = self.orchestrator.run(target_date=target, deadline=deadline, deep_mode=self.deep_mode, lite_mode=self.lite_mode)
            logger.info(
                "流水线执行完成: 筛选 %d 只, 分析完成 %d 只, 报告: %s",
                result.total_filtered,
                result.analysis_completed,
                result.report_path,
            )
        except Exception as e:
            logger.error("流水线执行异常: %s", e, exc_info=True)

    def _run_researcher(self):
        """策略研究员定时任务：每天 10:00 触发，仅交易日执行"""
        from datetime import date

        today = date.today()
        if not self._is_date_trading_day(today):
            logger.info("今天 %s 不是交易日，策略研究员跳过", today)
            return

        logger.info("策略研究员触发: %s", today)
        try:
            from strategy_researcher.researcher import StrategyResearcher
            researcher = StrategyResearcher()
            researcher.run()
            logger.info("策略研究员执行完成")
        except Exception as e:
            logger.error("策略研究员执行异常: %s", e, exc_info=True)
