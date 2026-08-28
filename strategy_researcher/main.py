#!/usr/bin/env python3
"""
策略研究员 Agent - 入口脚本

用法：
    # 立即执行一次 + 启动定时调度（每交易日 10:00）
    python -m strategy_researcher.main --run

    # 仅立即执行一次
    python -m strategy_researcher.main --now

    # 初始化 wiki 目录
    python -m strategy_researcher.main --init
"""

import argparse
import logging
import sys
import signal
from pathlib import Path
from datetime import date, timedelta

# 确保项目根目录在 path 中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _force_exit(sig, frame):
    print("\n[strategy_researcher] 收到中断信号，退出...")
    import os
    os._exit(0)


signal.signal(signal.SIGINT, _force_exit)
signal.signal(signal.SIGTERM, _force_exit)


def setup_logging():
    """配置日志"""
    from logging.handlers import TimedRotatingFileHandler

    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = TimedRotatingFileHandler(
        filename=str(log_dir / "strategy_researcher.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"

    logging.basicConfig(
        level=logging.INFO,
        handlers=[console_handler, file_handler],
    )


def _is_trading_day(d: date) -> bool:
    """判断是否为交易日"""
    if d.weekday() >= 5:
        return False
    try:
        from chinese_calendar import is_holiday
        return not is_holiday(d)
    except ImportError:
        return True


def main():
    parser = argparse.ArgumentParser(description="策略研究员 Agent")
    parser.add_argument("--run", action="store_true",
                        help="立即执行 + 启动定时调度（每交易日 10:00）")
    parser.add_argument("--now", action="store_true",
                        help="立即执行一次")
    parser.add_argument("--init", action="store_true",
                        help="初始化 wiki 目录结构")
    args = parser.parse_args()

    if not any([args.run, args.now, args.init]):
        parser.print_help()
        sys.exit(0)

    setup_logging()
    logger = logging.getLogger("strategy_researcher")

    # 初始化
    if args.init:
        from strategy_researcher.wiki_manager import init_wiki
        init_wiki()
        logger.info("Wiki 初始化完成")
        if not args.run and not args.now:
            return

    # 立即执行
    if args.now:
        from strategy_researcher.researcher import StrategyResearcher
        researcher = StrategyResearcher()
        try:
            researcher.run()
        except Exception as e:
            logger.error("执行失败: %s", e, exc_info=True)
        return

    # --run 模式：立即执行 + 定时调度
    if args.run:
        from strategy_researcher.researcher import StrategyResearcher

        logger.info("策略研究员启动: 立即执行 + 每交易日 10:00 调度")

        # 立即执行一次
        researcher = StrategyResearcher()
        try:
            researcher.run()
            logger.info("首次执行完成")
        except Exception as e:
            logger.error("首次执行失败: %s", e, exc_info=True)

        # 启动定时调度
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BlockingScheduler()

        def _scheduled_run():
            """定时触发"""
            today = date.today()
            if not _is_trading_day(today):
                logger.info("今天 %s 不是交易日，跳过", today)
                return
            logger.info("定时任务触发: %s", today)
            r = StrategyResearcher()
            try:
                r.run()
            except Exception as e:
                logger.error("定时执行失败: %s", e, exc_info=True)

        trigger = CronTrigger(hour=10, minute=0)
        scheduler.add_job(_scheduled_run, trigger, id="strategy_researcher",
                          misfire_grace_time=60)
        logger.info("定时调度已启动: 每天 10:00 触发（自动跳过非交易日）")
        scheduler.start()


if __name__ == "__main__":
    main()
