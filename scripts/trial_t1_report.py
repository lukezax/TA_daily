#!/usr/bin/env python3
"""试生成 T+1 研判报告：从最新 B1 CSV 取前 N 只股票，跑快速分析并渲染 HTML。

只读本地 CSV，不拉取新行情；输出到 /tmp/opencode/t1_trial_reports，不覆盖正式报告。
用法: python3 scripts/trial_t1_report.py [股票数量，默认2]
"""

import csv
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.analysis_client import TradingAgentsClient
from pipeline.config import load_config
from pipeline.models import FilterResults, StockFilterData
from pipeline.report_generator import ReportGenerator

OUT_DIR = Path("/tmp/opencode/t1_trial_reports")
ANALYSIS_DATE = "2026-11-20"  # 最近交易日；不重新拉取行情
DEPTH = "快速"
ANALYSTS = ["market", "news", "yangjia"]  # 试跑用 3 位分析师，降低耗时
# 本地 27B 模型即使快速深度也要 45~50 分钟/只，需显式给足超时
API_BASE = os.getenv("TRIAL_API_BASE", "http://localhost:8000")
POLL_TIMEOUT = int(os.getenv("TRIAL_POLL_TIMEOUT", "3600"))


def pick_stocks(n):
    csvs = sorted((ROOT / "reports").glob("b1_filtered_*.csv"), reverse=True)
    if not csvs:
        raise RuntimeError("没有 B1 筛选 CSV")
    rows = [r for r in csv.DictReader(csvs[0].open(encoding="utf-8")) if r.get("结果") == "符合"]
    picked = rows[:n]
    print(f"数据源: {csvs[0].name}  符合 {len(rows)} 只，试跑 {len(picked)} 只")
    return picked, csvs[0].name


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    n = max(1, min(n, 3))
    rows, csv_name = pick_stocks(n)

    config = load_config()
    config.api_base_url = API_BASE
    config.report_output_dir = str(OUT_DIR)
    config.research_depth = DEPTH
    config.selected_analysts = ANALYSTS

    client = TradingAgentsClient(config)
    client._analysis_date = ANALYSIS_DATE
    if not client.is_available():
        raise RuntimeError("TradingAgents API 不可用")
    token = client.login()
    if not token:
        raise RuntimeError("登录失败")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    results = {}
    for row in rows:
        code = row["股票代码"]
        name = row.get("股票名称", "")
        stock = SimpleNamespace(code=code, name=name)
        print(f"提交 {code} {name} ...", flush=True)
        task_id = client.submit_one(stock, "local", headers, DEPTH)
        result = client.poll_one(stock, task_id, headers, POLL_TIMEOUT)
        print(f"  -> {result.status}  action={result.recommendation!r} direction={getattr(result,'direction','')!r}", flush=True)
        results[code] = result

    filter_stocks = [
        StockFilterData(
            code=r["股票代码"],
            name=r.get("股票名称", ""),
            exchange=r.get("交易所", ""),
            result=True,
            tags=["B1"],
            details={
                "新增条件总分": int(float(r.get("新增条件总分", 0) or 0)),
                "收盘价": float(r.get("收盘价", 0) or 0),
                "涨幅": float(r.get("涨幅", 0) or 0),
                "振幅": float(r.get("振幅", 0) or 0),
            },
        )
        for r in rows
    ]
    filter_data = FilterResults(date=ANALYSIS_DATE, total_scanned=len(rows), stocks=filter_stocks)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generator = ReportGenerator(config)
    path = generator.generate(ANALYSIS_DATE, filter_data, results)
    text = path.read_text(encoding="utf-8")
    print(f"报告已生成: {path}")
    print(f"含 T+1 方向: {'T+1 方向' in text}  含目标价: {'目标价' in text}  大小: {len(text)} 字符")


if __name__ == "__main__":
    main()
