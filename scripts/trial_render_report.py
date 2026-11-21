#!/usr/bin/env python3
"""用已完成的历史分析结果渲染新模板报告（不调用 LLM、不拉新数据）。

用法: python3 scripts/trial_render_report.py
输出: /tmp/opencode/t1_trial_reports/2026-11-20.html
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.analysis_client import _as_float
from pipeline.config import load_config
from pipeline.models import FilterResults, StockFilterData, StockAnalysisResult
from pipeline.report_generator import ReportGenerator
from pipeline.report_reader import TradingAgentsReportReader

# 写到报告服务目录，浏览器可直接打开：
# http://<host>:8222/trial_t1_2026-11-20.html
OUT_DIR = Path(__file__).resolve().parents[1] / "reports"
DATE = "2026-11-20"
CODES = [
    ("600436.SH", "片仔癀", "SH"),
    ("603198.SH", "迎驾贡酒", "SH"),
    ("605117.SH", "德业股份", "SH"),
]


def to_pct(value) -> float:
    """报告里的置信度/风险已经是 0-100；只在万一为 0-1 小数时换算。"""
    number = _as_float(value)
    return number * 100 if number <= 1 else number


def main():
    config = load_config()
    config.report_output_dir = str(OUT_DIR)
    reader = TradingAgentsReportReader(config.tradingagents_results_dir)

    filter_stocks = []
    results = {}
    for code, name, exchange in CODES:
        decision = reader.read_final_decision(code, DATE) or {}
        print(f"{code} {name}: action={decision.get('action')!r} direction={decision.get('direction')!r}")
        filter_stocks.append(
            StockFilterData(
                code=code, name=name, exchange=exchange, result=True, tags=["B1"],
                details={"新增条件总分": 3, "收盘价": 0, "涨幅": 0, "振幅": 0},
            )
        )
        results[code] = StockAnalysisResult(
            code=code,
            status="completed",
            recommendation=decision.get("action", ""),
            direction=decision.get("direction", ""),
            confidence_score=to_pct(decision.get("confidence", 0)),
            risk_score=to_pct(decision.get("risk_score", 0)),
            summary=decision.get("summary", ""),
        )

    filter_data = FilterResults(date=DATE, total_scanned=3, stocks=filter_stocks)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = ReportGenerator(config).generate(DATE, filter_data, results)
    served = OUT_DIR / f"trial_t1_{DATE}.html"
    path.rename(served)
    text = served.read_text(encoding="utf-8")
    print(f"报告: {served}")
    print(f"含 T+1 方向: {'T+1 方向' in text}  含目标价: {'目标价' in text}  大小: {len(text)} 字符")


if __name__ == "__main__":
    main()
