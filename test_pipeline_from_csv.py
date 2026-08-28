#!/usr/bin/env python3
"""
测试脚本：从已有的 CSV 筛选结果出发，测试流水线后半段
（跳过 stock_filter 执行，直接用 CSV 数据 → TradingAgents 分析 → 生成报告）
"""

import csv
import logging
import sys
from pathlib import Path

from pipeline.config import load_config
from pipeline.models import FilterResults, StockFilterData, StockAnalysisResult
from pipeline.analysis_client import TradingAgentsClient
from pipeline.report_generator import ReportGenerator
from pipeline.report_reader import TradingAgentsReportReader

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_pipeline")


def load_filter_results_from_csv(csv_path: str) -> FilterResults:
    """从 CSV 文件加载筛选结果"""
    stocks = []
    total_rows = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            # 只取符合条件的
            if row.get("结果") != "符合":
                continue
            if row.get("状态") != "成功":
                continue

            # 构建 details dict（保留所有字段）
            details = {}
            skip_keys = {"股票代码", "股票名称", "交易所", "状态", "结果", "message"}
            for key, value in row.items():
                if key in skip_keys:
                    continue
                # 尝试转换为数值
                if value == "True":
                    details[key] = True
                elif value == "False":
                    details[key] = False
                elif value == "" or value is None:
                    details[key] = None
                else:
                    try:
                        details[key] = float(value)
                    except (ValueError, TypeError):
                        details[key] = value

            stock = StockFilterData(
                code=row["股票代码"],
                name=row["股票名称"],
                exchange=row["交易所"],
                result=True,
                details=details,
            )
            stocks.append(stock)

    logger.info("从 CSV 加载: 总行数 %d, 符合条件 %d 只", total_rows, len(stocks))
    return FilterResults(
        date="2026-05-07",
        total_scanned=total_rows,
        stocks=stocks,
    )


def main():
    csv_path = "/home/lima/workspace/stock/b1_filtered_stocks_20260507_033006.csv"

    if not Path(csv_path).exists():
        logger.error("CSV 文件不存在: %s", csv_path)
        sys.exit(1)

    # 加载配置
    config = load_config()
    logger.info("配置加载完成")

    # 从 CSV 加载筛选结果
    filter_results = load_filter_results_from_csv(csv_path)
    logger.info(
        "筛选结果: %d 只股票通过（总扫描 %d）",
        filter_results.total_passed,
        filter_results.total_scanned,
    )

    if not filter_results.stocks:
        logger.warning("无符合条件的股票，生成空报告")
        report_gen = ReportGenerator(config)
        path = report_gen.generate_empty_report(filter_results.date)
        logger.info("空报告已生成: %s", path)
        return

    # 打印符合条件的股票
    for s in filter_results.stocks:
        logger.info("  %s %s (得分: %d)", s.code, s.name, s.total_score)

    # 尝试 AI 分析
    analysis_results = {}
    client = TradingAgentsClient(config)

    if client.is_available():
        logger.info("TradingAgents 服务可用，开始提交分析...")
        analysis_results = client.analyze_batch(
            stocks=filter_results.stocks,
            timeout_per_stock=config.timeout_per_stock,
        )
        logger.info("分析完成: %d 只获得结果", len(analysis_results))
    else:
        logger.warning("TradingAgents 服务不可用，跳过 AI 分析")

    # 生成报告
    report_gen = ReportGenerator(config)
    report_path = report_gen.generate(
        date=filter_results.date,
        filter_data=filter_results,
        analysis_data=analysis_results,
    )
    report_gen.generate_index()

    logger.info("报告已生成: %s", report_path)
    logger.info("可通过以下命令启动 HTTP 服务查看:")
    logger.info("  python -m pipeline.main --serve")


if __name__ == "__main__":
    main()
