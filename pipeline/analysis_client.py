"""
TradingAgents-CN API 客户端
提交单股分析任务并轮询结果。
"""

import logging
import time
from typing import Optional

import requests

from pipeline.config import PipelineConfig
from pipeline.models import StockAnalysisResult

logger = logging.getLogger(__name__)


class TradingAgentsClient:
    """TradingAgents-CN API 客户端"""

    def __init__(self, config: PipelineConfig):
        self.base_url = config.api_base_url.rstrip("/")
        self.username = config.api_username
        self.password = config.api_password
        self.research_depth = config.research_depth
        self.selected_analysts = config.selected_analysts
        self._poll_interval = 30
        self._max_consecutive_conn_errors = 10
        self._analysis_date = ""

    def is_available(self) -> bool:
        """检查 TradingAgents 服务是否可用"""
        try:
            resp = requests.get(f"{self.base_url}/api/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            logger.warning("TradingAgents 服务不可用")
            return False

    def _login(self) -> Optional[str]:
        """登录获取 JWT Token,重试 3 次。"""
        max_retries = 3
        backoff = 2

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    f"{self.base_url}/api/auth/login",
                    json={"username": self.username, "password": self.password},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    token = data.get("data", {}).get("access_token")
                    if token:
                        logger.info("TradingAgents 登录成功")
                        return token
                    logger.warning("登录响应中未找到 access_token")
                else:
                    logger.warning(
                        "登录失败 (attempt %d/%d): HTTP %d",
                        attempt, max_retries, resp.status_code,
                    )
            except Exception as e:
                logger.warning(
                    "登录异常 (attempt %d/%d): %s", attempt, max_retries, e
                )

            if attempt < max_retries:
                time.sleep(backoff * attempt)

        logger.error("TradingAgents 登录失败,已重试 %d 次", max_retries)
        return None

    def login(self) -> Optional[str]:
        """公开登录方法,供调度器调用。"""
        return self._login()

    def _normalize_code(self, code: str) -> str:
        """去掉股票代码后缀,TradingAgents 只接受纯 6 位数字。"""
        return code.split(".")[0]

    def submit_one(self, stock, model_name: str, headers: dict) -> str:
        """提交单只股票分析,返回 task_id。"""
        symbol = self._normalize_code(stock.code)
        payload = {
            "title": "Pipeline单股分析",
            "symbols": [symbol],
            "parameters": {
                "market_type": "A股",
                "analysis_date": self._analysis_date,
                "research_depth": self.research_depth,
                "selected_analysts": self.selected_analysts,
                "include_sentiment": True,
                "include_risk": True,
                "language": "zh-CN",
                "quick_analysis_model": model_name,
                "deep_analysis_model": model_name,
            },
        }
        resp = requests.post(
            f"{self.base_url}/api/analysis/batch",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"提交失败: HTTP {resp.status_code}")
        resp_data = resp.json()
        data_obj = resp_data.get("data", resp_data)
        task_ids = data_obj.get("task_ids", [])
        if not task_ids:
            raise RuntimeError(f"未返回 task_ids: {resp_data}")
        return task_ids[0]

    def poll_one(
        self, stock, task_id: str, headers: dict, timeout: int
    ) -> StockAnalysisResult:
        """轮询单个任务直到 completed / failed / timeout。"""
        start_time = time.time()
        consecutive_401 = 0
        consecutive_conn_errors = 0

        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                logger.warning("股票 %s 分析超时(%.0fs)", stock.code, elapsed)
                return StockAnalysisResult(
                    code=stock.code,
                    status="timeout",
                    execution_time=elapsed,
                    error_message=f"分析超时({timeout}s)",
                )

            try:
                resp = requests.get(
                    f"{self.base_url}/api/analysis/tasks/{task_id}/status",
                    headers=headers,
                    timeout=10,
                )
                consecutive_conn_errors = 0
                if resp.status_code == 401:
                    consecutive_401 += 1
                    if consecutive_401 >= 3:
                        logger.warning(
                            "股票 %s 连续 %d 次 401,尝试刷新 Token...",
                            stock.code, consecutive_401,
                        )
                        new_token = self._login()
                        if new_token:
                            headers["Authorization"] = f"Bearer {new_token}"
                            logger.info("Token 刷新成功,继续轮询")
                            consecutive_401 = 0
                        else:
                            logger.error("Token 刷新失败")
                    time.sleep(self._poll_interval)
                    continue
                elif resp.status_code != 200:
                    logger.warning(
                        "查询任务 %s 状态失败: HTTP %d", task_id, resp.status_code
                    )
                    consecutive_401 = 0
                    time.sleep(self._poll_interval)
                    continue

                consecutive_401 = 0
                status_data = resp.json().get("data", {})
                status = status_data.get("status", "")

                if status == "completed":
                    logger.info("股票 %s 分析完成(%.0fs)", stock.code, elapsed)
                    return self._fetch_result(task_id, stock, headers, elapsed)

                if status == "failed":
                    error_msg = status_data.get("error", "分析失败")
                    logger.error("股票 %s 分析失败: %s", stock.code, error_msg)
                    return StockAnalysisResult(
                        code=stock.code,
                        status="failed",
                        execution_time=elapsed,
                        error_message=error_msg,
                    )

                logger.info("股票 %s 状态: %s(%.0fs)", stock.code, status, elapsed)

            except requests.exceptions.ConnectionError as e:
                consecutive_conn_errors += 1
                if consecutive_conn_errors >= self._max_consecutive_conn_errors:
                    logger.error(
                        "任务 %s(股票 %s)连续 %d 次连接失败,判定服务不可用",
                        task_id, stock.code, consecutive_conn_errors,
                    )
                    return StockAnalysisResult(
                        code=stock.code,
                        status="failed",
                        execution_time=elapsed,
                        error_message=f"TradingAgents 服务不可用(连续 {consecutive_conn_errors} 次连接失败)",
                    )
                logger.warning(
                    "轮询任务 %s 连接失败(%d/%d): %s",
                    task_id, consecutive_conn_errors,
                    self._max_consecutive_conn_errors, e,
                )
            except Exception as e:
                logger.warning("轮询任务 %s 异常: %s", task_id, e)
                consecutive_401 = 0
                consecutive_conn_errors = 0

            time.sleep(self._poll_interval)

    def _fetch_result(
        self, task_id: str, stock, headers: dict, elapsed: float
    ) -> StockAnalysisResult:
        """获取已完成任务的详细结果"""
        try:
            resp = requests.get(
                f"{self.base_url}/api/analysis/tasks/{task_id}/result",
                headers=headers,
                timeout=30,
            )
            if resp.status_code != 200:
                logger.error(
                    "获取任务 %s 结果失败: HTTP %d", task_id, resp.status_code
                )
                return StockAnalysisResult(
                    code=stock.code,
                    status="failed",
                    execution_time=elapsed,
                    error_message=f"获取结果失败: HTTP {resp.status_code}",
                )

            data = resp.json().get("data", {})

            reports = {}
            raw_reports = data.get("reports", {})
            if isinstance(raw_reports, dict):
                reports = raw_reports

            decision = data.get("decision", {})

            raw_confidence = float(
                data.get("confidence_score", decision.get("confidence", 0))
            )
            raw_risk = float(decision.get("risk_score", 0))

            confidence_pct = (
                raw_confidence * 100 if raw_confidence <= 1 else raw_confidence
            )
            risk_pct = raw_risk * 100 if raw_risk <= 1 else raw_risk

            return StockAnalysisResult(
                code=stock.code,
                status="completed",
                recommendation=data.get("recommendation", decision.get("action", "")),
                confidence_score=confidence_pct,
                risk_score=risk_pct,
                risk_level=data.get("risk_level", ""),
                target_price=float(decision.get("target_price", 0)),
                summary=data.get("summary", decision.get("reasoning", "")),
                analyst_reports=reports,
                execution_time=elapsed,
            )

        except Exception as e:
            logger.error("解析任务 %s 结果异常: %s", task_id, e)
            return StockAnalysisResult(
                code=stock.code,
                status="failed",
                execution_time=elapsed,
                error_message=f"结果解析异常: {e}",
            )
