#!/usr/bin/env python3
"""回归测试：deadline 分叉修复 + 轮询快速失败

覆盖两起事故：
1. 2026-08-24 00:03 过零点手动启动 → 报告日 8-24 但 deadline 算成 8-25 09:00，
   流水线在 24 日全天持续提交批次（next_trading_day 的 9:30 分界修复）
2. TradingAgents 服务 20:31 停止后，_poll_task 空转轮询 3 小时直到超时
   （连续 ConnectionError 快速失败修复）

运行: python test_pipeline_fixes.py
"""
from datetime import date, datetime
from unittest.mock import patch

import requests

from pipeline.orchestrator import next_trading_day
from pipeline.analysis_client import TradingAgentsClient
from pipeline.config import PipelineConfig
from pipeline.models import StockFilterData


def test_next_trading_day_boundary():
    report = next_trading_day(datetime(2026, 8, 24, 0, 3, 22))
    assert report == date(2026, 8, 24), report
    deadline = datetime.combine(report, datetime.min.time()).replace(hour=9)
    assert deadline == datetime(2026, 8, 24, 9, 0), deadline

    assert next_trading_day(datetime(2026, 8, 24, 10, 0)) == date(2026, 8, 25)
    assert next_trading_day(datetime(2026, 8, 21, 21, 0)) == date(2026, 8, 24)
    assert next_trading_day(datetime(2026, 8, 22, 0, 3)) == date(2026, 8, 24)


def test_poll_task_fast_fail_when_service_down():
    client = TradingAgentsClient(PipelineConfig(api_username="x", api_password="y"))
    client._poll_interval = 0
    client._max_consecutive_conn_errors = 3

    stock = StockFilterData(code="600000.SH", name="测试", exchange="SH", result=True)

    def conn_refused(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Connection refused")

    with patch("pipeline.analysis_client.requests.get", side_effect=conn_refused):
        result = client._poll_task("task-1", stock, {}, timeout_per_stock=60)

    assert result.status == "failed", result.error_message
    assert "服务不可用" in result.error_message, result.error_message


if __name__ == "__main__":
    test_next_trading_day_boundary()
    test_poll_task_fast_fail_when_service_down()
    print("all tests passed")
