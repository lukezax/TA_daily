"""
缠论高分扫描器（缠高分通道）

每日对全市场股票执行缠论脚本分析（纯 CZSC 算法，无 LLM），
输出 trend_score >= 阈值（默认 8 分）的股票列表，作为独立筛选分类
"缠高分" 加入分析流程，与 B1/B2严格/B2宽松 并列。
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from czsc import CZSC, format_standard_kline

from pipeline.models import StockFilterData

# TradingAgents-CN 的 czsc_analyst 不在默认 sys.path，需显式注入（与 data_preheater 一致）
_TA_PATH = Path(__file__).resolve().parents[1] / "TradingAgents-CN"
if str(_TA_PATH) not in sys.path:
    sys.path.insert(0, str(_TA_PATH))

logger = logging.getLogger("pipeline.czsc_scanner")

CZSC_HIGH_SCORE_TAG = "缠高分"
DEFAULT_THRESHOLD = 8


def is_excluded(code: str, name: str) -> bool:
    """与 stock_filter 相同的剔除规则：创业板/科创板/ST/退市"""
    c = code.split(".")[0]
    if c.startswith(("300", "301", "302", "688")):
        return True
    if name.startswith(("ST", "*ST")):
        return True
    if "退市" in name:
        return True
    return False


def load_stock_pool(stock_list_file: Optional[Path] = None) -> List[dict]:
    """
    加载全市场股票列表（code/name/exchange），剔除创业板/科创板/ST/退市。

    Args:
        stock_list_file: stock_list_all.json 路径，默认 stock_data/stock_list_all.json

    Returns:
        过滤后的股票列表 [{code, name, exchange}]
    """
    if stock_list_file is None:
        stock_list_file = Path("stock_data/stock_list_all.json")
    if not stock_list_file.exists():
        logger.warning("股票列表文件不存在: %s", stock_list_file)
        return []

    raw = json.loads(stock_list_file.read_text(encoding="utf-8"))
    stock_list = raw.get("data", raw) if isinstance(raw, dict) else raw
    pool = [s for s in stock_list if not is_excluded(s["code"], s["name"])]
    logger.info("全市场股票池: %d 只（剔除创业板/科创板/ST/退市）", len(pool))
    return pool


def _load_bars(code: str, data_dir: Path):
    """读取单只股票日K并转为 CZSC RawBar（本地无数据或不足120根时返回 None）"""
    f = data_dir / f"{code}_d.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))["data"]
    if len(data) < 120:
        return None
    code6 = code.split(".")[0]
    records = []
    for x in data[-250:]:
        records.append({
            "dt": x["t"],
            "symbol": code6,
            "open": float(x["o"]),
            "close": float(x["c"]),
            "high": float(x["h"]),
            "low": float(x["l"]),
            "vol": float(x["v"]),
            "amount": float(x.get("a", 0) or 0),
        })
    return format_standard_kline(pd.DataFrame(records), freq="日线")


def _compute_trend_score(code: str, data_dir: Path) -> Optional[dict]:
    """对单只股票执行缠论分析，返回 {trend_score, trend, buy_signals, sell_signals} 或 None"""
    try:
        from tradingagents.agents.analysts.czsc_analyst import _extract_czsc_signals

        bars = _load_bars(code, data_dir)
        if bars is None:
            return None
        signals = _extract_czsc_signals(CZSC(bars))
        return {
            "trend_score": signals.get("trend_score", 0),
            "trend": signals.get("trend", ""),
            "buy_signals": signals.get("buy_signals", []),
            "sell_signals": signals.get("sell_signals", []),
        }
    except Exception as e:
        logger.debug("缠论分析异常 %s: %s", code, e)
        return None


def scan_high_score(
    threshold: int = DEFAULT_THRESHOLD,
    stock_list_file: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> tuple:
    """
    全市场缠论扫描，返回 (缠高分股票列表, 扫描池大小)。

    Args:
        threshold: 缠论评分阈值（默认 8）
        stock_list_file: 股票列表路径，默认 stock_data/stock_list_all.json
        data_dir: K线数据目录，默认 stock_data

    Returns:
        (List[StockFilterData], int):
            - 缠高分股票列表（StockFilterData，tags=["缠高分"]，details 含评分/趋势/信号）
            - 实际扫描的股票池大小（用于更新 total_scanned）
    """
    if data_dir is None:
        data_dir = Path("stock_data")

    pool = load_stock_pool(stock_list_file)
    results: List[StockFilterData] = []
    scored = 0
    no_data = 0
    t0 = time.time()

    for i, s in enumerate(pool):
        code = s["code"]
        sig = _compute_trend_score(code, data_dir)
        if sig is None:
            no_data += 1
            continue
        scored += 1
        if sig["trend_score"] >= threshold:
            results.append(StockFilterData(
                code=code,
                name=s["name"],
                exchange=s.get("exchange", ""),
                result=True,
                tags=[CZSC_HIGH_SCORE_TAG],
                details={
                    "缠论评分": sig["trend_score"],
                    "缠论趋势": sig["trend"],
                    "买入信号": sig["buy_signals"],
                    "卖出信号": sig["sell_signals"],
                },
            ))
            logger.info("缠高分: %s %s 评分=%d 趋势=%s",
                        code, s["name"], sig["trend_score"], sig["trend"])

        if (i + 1) % 1000 == 0:
            logger.info("缠论扫描进度: %d/%d", i + 1, len(pool))

    elapsed = time.time() - t0
    logger.info(
        "缠论扫描完成: 扫描 %d 只, 成功评分 %d 只, 无本地K线 %d 只, "
        "缠高分(>=%d) %d 只, 耗时 %.1fs",
        len(pool), scored, no_data, threshold, len(results), elapsed,
    )
    return results, len(pool)
