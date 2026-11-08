"""
历史买入扫描器

扫描全市场股票，找出全局最近 N 次流水线运行结果中 final_trade_decision.md 行动="买入"的股票，
作为独立筛选分类 "历史买入" 加入分析流程。
"""

import logging
import re
from pathlib import Path
from typing import List, Optional

from pipeline.czsc_scanner import is_excluded, load_stock_pool
from pipeline.models import StockFilterData

logger = logging.getLogger("pipeline.historical_buy_scanner")

HISTORICAL_BUY_TAG = "历史买入"

BUY_ACTION_RE = re.compile(r"行动[^：:\n]{0,4}[：:]\s*买入")
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _get_recent_report_dates(report_dir: Path, lookback: int = 3) -> List[str]:
    """从 reports/*.html 文件名提取最近 N 个结果日期（排除 index.html）"""
    dates = []
    for f in report_dir.glob("*.html"):
        name = f.stem
        if name == "index":
            continue
        if DATE_DIR_RE.match(name):
            dates.append(name)
    dates.sort(reverse=True)
    return dates[:lookback]


def _is_buy_decision(md_text: str) -> bool:
    """检查 final_trade_decision.md 中行动是否为买入"""
    if not md_text:
        return False
    return bool(BUY_ACTION_RE.search(md_text))


def _check_stock_historical_buy(
    code: str,
    results_dir: Path,
    recent_dates: List[str],
) -> Optional[dict]:
    """
    检查单只股票在指定日期列表中是否有买入决策。

    Returns:
        包含买入信息的 dict 或 None
    """
    code6 = code.split(".")[0]
    buy_dates = []

    for date_str in recent_dates:
        report_file = results_dir / code6 / date_str / "reports" / "final_trade_decision.md"
        if not report_file.exists():
            continue
        try:
            content = report_file.read_text(encoding="utf-8")
            if _is_buy_decision(content):
                buy_dates.append(date_str)
        except (IOError, UnicodeDecodeError):
            continue

    if not buy_dates:
        return None

    return {
        "buy_dates": buy_dates,
        "buy_count": len(buy_dates),
    }


def scan_historical_buy(
    lookback: int = 3,
    stock_list_file: Optional[Path] = None,
    results_dir: Optional[Path] = None,
    report_dir: Optional[Path] = None,
) -> tuple:
    """
    全市场扫描，返回 (历史买入股票列表, 扫描池大小)。

    Args:
        lookback: 检查最近 N 次流水线结果（默认 3）
        stock_list_file: 股票列表路径，默认 stock_data/stock_list_all.json
        results_dir: TradingAgents 结果目录，默认 TradingAgents-CN/results
        report_dir: 报告目录，默认 reports

    Returns:
        (List[StockFilterData], int):
            - 历史买入股票列表
            - 实际扫描的股票池大小
    """
    if results_dir is None:
        results_dir = Path("TradingAgents-CN/results")
    if report_dir is None:
        report_dir = Path("reports")

    pool = load_stock_pool(stock_list_file)
    recent_dates = _get_recent_report_dates(report_dir, lookback)

    if not recent_dates:
        logger.warning("未找到报告日期，历史买入扫描跳过")
        return [], len(pool)

    logger.info(
        "历史买入扫描: 检查最近 %d 次结果 (%s)",
        lookback,
        ", ".join(recent_dates),
    )

    results: List[StockFilterData] = []
    scanned = 0

    for s in pool:
        code = s["code"]
        scanned += 1

        buy_info = _check_stock_historical_buy(code, results_dir, recent_dates)
        if buy_info is None:
            continue

        results.append(StockFilterData(
            code=code,
            name=s["name"],
            exchange=s.get("exchange", ""),
            result=True,
            tags=[HISTORICAL_BUY_TAG],
            details={
                "买入日期": buy_info["buy_dates"],
                "买入次数": buy_info["buy_count"],
            },
        ))
        logger.info(
            "历史买入: %s %s 买入 %d 天 (%s)",
            code,
            s["name"],
            buy_info["buy_count"],
            ", ".join(buy_info["buy_dates"]),
        )

    logger.info(
        "历史买入扫描完成: 扫描 %d 只, 符合条件 %d 只",
        scanned,
        len(results),
    )
    return results, scanned
