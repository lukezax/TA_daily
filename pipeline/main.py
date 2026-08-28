#!/usr/bin/env python3
"""
股票筛选分析流水线 - 入口脚本

用法:
    # 立即执行一次 + 启动定时调度 + HTTP 服务（一条命令搞定，后台持续运行）
    nohup python -m pipeline.main --run &

    # 指定执行时间（覆盖配置文件中的 schedule_time）
    nohup python -m pipeline.main --run --time 01:30 &

    # 仅立即执行一次（不启动调度和服务）
    python -m pipeline.main --now

    # 仅启动 HTTP 报告服务
    python -m pipeline.main --serve

    # 仅启动定时调度（不含 HTTP 服务）
    python -m pipeline.main --schedule --time 02:00
"""

import argparse
import logging
import sys
import signal
import threading

from pipeline.config import load_config
from pipeline.orchestrator import PipelineOrchestrator, PipelineScheduler, next_trading_day
from pipeline.report_server import ReportServer
from pipeline.report_generator import ReportGenerator


def _force_exit(sig, frame):
    """Ctrl+C 强制退出"""
    print("\n[pipeline] 收到中断信号，正在退出...")
    import os
    os._exit(0)  # 强制退出，不等待线程


signal.signal(signal.SIGINT, _force_exit)
signal.signal(signal.SIGTERM, _force_exit)


def setup_logging():
    """配置日志：按天轮转，保留 30 天"""
    from logging.handlers import TimedRotatingFileHandler
    from pathlib import Path

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 按天轮转文件，保留 30 天
    file_handler = TimedRotatingFileHandler(
        filename=str(log_dir / "pipeline.log"),
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


def main():
    parser = argparse.ArgumentParser(description="股票筛选分析流水线")
    parser.add_argument("--run", action="store_true",
                        help="完整模式：立即执行一次 + 启动定时调度 + HTTP 服务（推荐，一条命令持续运行）")
    parser.add_argument("--now", action="store_true", help="立即执行一次流水线")
    parser.add_argument("--serve", action="store_true", help="启动 HTTP 报告服务")
    parser.add_argument("--schedule", action="store_true", help="启动定时调度")
    parser.add_argument("--time", type=str, default=None,
                        help="指定每日执行时间（HH:MM 格式），覆盖配置文件中的 schedule_time")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径")
    parser.add_argument("--debug", action="store_true",
                        help="调试模式：不更新数据（跳过市值快筛和API拉取），只用本地缓存跑筛选+分析流程")
    args = parser.parse_args()

    if not any([args.run, args.now, args.serve, args.schedule]):
        parser.print_help()
        sys.exit(0)

    setup_logging()
    logger = logging.getLogger("pipeline")

    # 加载配置
    config = load_config(args.config)

    # debug 模式提示
    if args.debug:
        logger.info("🔧 调试模式：跳过数据更新，使用本地缓存数据")

    # 如果指定了 --time，覆盖配置中的 schedule_time
    if args.time:
        # 校验格式
        try:
            h, m = args.time.split(":")
            int(h)
            int(m)
            config.schedule_time = args.time
            logger.info("执行时间已覆盖为: %s", args.time)
        except (ValueError, AttributeError):
            print(f"[错误] --time 格式无效: {args.time}，应为 HH:MM（如 01:30）", file=sys.stderr)
            sys.exit(1)

    logger.info("配置加载完成: api=%s, port=%d, schedule=%s",
                config.api_base_url, config.server_port, config.schedule_time)

    # --run 模式：立即执行 + 定时调度 + HTTP 服务（一条命令搞定）
    if args.run:
        logger.info("=" * 60)
        logger.info("完整模式启动：立即执行 + 定时调度(%s) + HTTP服务(:%d)",
                    config.schedule_time, config.server_port)
        logger.info("=" * 60)

        # 1. 先启动 HTTP 服务（后台线程），确保随时可访问
        report_gen = ReportGenerator(config)
        report_gen.generate_index()
        server = ReportServer(config)

        def run_http():
            server.start()

        http_thread = threading.Thread(target=run_http, daemon=True)
        http_thread.start()
        logger.info("HTTP 报告服务已启动: http://0.0.0.0:%d", config.server_port)

        # 2. 立即执行一次
        # 报告日期与截止时间由同一次交易日计算推导（截止 = 报告日当天 09:00），
        # 避免过零点手动启动时 deadline 落到后天
        from datetime import datetime as _dt
        _report_date = next_trading_day()
        _deadline = _dt.combine(_report_date, _dt.min.time()).replace(hour=9, minute=0)
        logger.info("首次执行: 报告日期 %s，截止时间 %s", _report_date, _deadline.strftime("%Y-%m-%d %H:%M"))

        orchestrator = PipelineOrchestrator(config)
        try:
            result = orchestrator.run(target_date=_report_date, debug=args.debug, deadline=_deadline)
            logger.info(
                "首次执行完成: 筛选 %d 只, 分析完成 %d 只, 报告: %s",
                result.total_filtered,
                result.analysis_completed,
                result.report_path,
            )
        except Exception as e:
            logger.error("首次执行失败: %s", e, exc_info=True)

        # 3. 启动定时调度（阻塞主线程）
        scheduler = PipelineScheduler(config)
        logger.info("定时调度启动: 每交易日 %s", config.schedule_time)
        scheduler.start()  # 阻塞
        return

    # 立即执行
    if args.now:
        logger.info("开始立即执行流水线")
        orchestrator = PipelineOrchestrator(config)
        try:
            result = orchestrator.run(debug=args.debug)
            logger.info(
                "流水线完成: 筛选 %d 只, 分析完成 %d 只, 报告: %s",
                result.total_filtered,
                result.analysis_completed,
                result.report_path,
            )
        except Exception as e:
            logger.error("流水线执行失败: %s", e, exc_info=True)
            if not args.serve:
                sys.exit(1)

    # 启动 HTTP 服务
    if args.serve:
        report_gen = ReportGenerator(config)
        report_gen.generate_index()
        server = ReportServer(config)
        logger.info("启动 HTTP 报告服务: http://0.0.0.0:%d", config.server_port)
        server.start()

    # 启动定时调度
    elif args.schedule:
        scheduler = PipelineScheduler(config)
        scheduler.start()


if __name__ == "__main__":
    main()
