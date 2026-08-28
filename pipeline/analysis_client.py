"""
TradingAgents-CN API 客户端
与 TradingAgents-CN API 交互，提交分析任务并收集结果
"""

import time
import logging
import concurrent.futures
from typing import Dict, List, Optional

import requests

from pipeline.config import PipelineConfig
from pipeline.models import StockFilterData, StockAnalysisResult

logger = logging.getLogger(__name__)


class TradingAgentsClient:
    """TradingAgents-CN API 客户端"""

    def __init__(self, config: PipelineConfig):
        self.base_url = config.api_base_url.rstrip("/")
        self.username = config.api_username
        self.password = config.api_password
        self.batch_size = config.batch_size
        self.timeout_per_stock = config.timeout_per_stock
        self._poll_interval = 30  # 轮询间隔（秒）
        self._max_consecutive_conn_errors = 10  # 连续连接失败判定阈值（30s×10≈5 分钟连不上即判定服务已停止）

    def is_available(self) -> bool:
        """检查 TradingAgents 服务是否可用"""
        try:
            resp = requests.get(f"{self.base_url}/api/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            logger.warning("TradingAgents 服务不可用")
            return False

    def _login(self) -> Optional[str]:
        """
        登录获取 JWT Token。
        重试 3 次，每次间隔 2s backoff。
        """
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

        logger.error("TradingAgents 登录失败，已重试 %d 次", max_retries)
        return None

    def analyze_batch(
        self,
        stocks: List[StockFilterData],
        timeout_per_stock: int = 1800,
    ) -> Dict[str, StockAnalysisResult]:
        """
        批量分析股票。

        - 自动分批（每批最多 batch_size 只，默认 10）
        - 轮询等待结果
        - 单只超时不影响其他股票
        - 服务不可用或登录失败时返回空 dict

        Returns:
            {stock_code: StockAnalysisResult}
        """
        if not stocks:
            return {}

        # 登录
        token = self._login()
        if not token:
            logger.error("无法登录 TradingAgents，跳过 AI 分析")
            return {}

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        results: Dict[str, StockAnalysisResult] = {}

        # 分批
        batches = [
            stocks[i : i + self.batch_size]
            for i in range(0, len(stocks), self.batch_size)
        ]

        for batch_idx, batch in enumerate(batches, 1):
            logger.info(
                "提交批次 %d/%d（%d 只股票）",
                batch_idx, len(batches), len(batch),
            )
            batch_results = self._process_batch(batch, headers, timeout_per_stock)
            results.update(batch_results)

        logger.info(
            "批量分析完成: %d/%d 只股票获得结果",
            sum(1 for r in results.values() if r.status == "completed"),
            len(stocks),
        )
        return results

    def _normalize_code(self, code: str) -> str:
        """去掉股票代码后缀，TradingAgents 只接受纯 6 位数字"""
        return code.split(".")[0]

    def login(self) -> Optional[str]:
        """
        公开登录方法，供编排器调用以获取 token。
        Returns:
            JWT token 或 None
        """
        return self._login()

    def process_single_batch(
        self,
        batch: List[StockFilterData],
        headers: Dict[str, str],
        timeout_per_stock: int,
        analysis_date: str = "",
        deadline=None,
        deep_mode: bool = False,
        lite_mode: bool = False,
    ) -> Dict[str, StockAnalysisResult]:
        """
        处理单个批次：提交 → 并行轮询 → 获取结果

        公开方法，供编排器直接调用以实现增量报告生成。

        Args:
            deep_mode: 若为 True，深度分析使用云端模型（qwen3.7-max），而非本地模型。
            lite_mode: 若为 True，辩论节点使用云端模型，数据收集保持本地。
        """
        return self._process_batch(batch, headers, timeout_per_stock, analysis_date, deadline, deep_mode=deep_mode, lite_mode=lite_mode)

    def _process_batch(
        self,
        batch: List[StockFilterData],
        headers: Dict[str, str],
        timeout_per_stock: int,
        analysis_date: str = "",
        deadline=None,
        deep_mode: bool = False,
        lite_mode: bool = False,
    ) -> Dict[str, StockAnalysisResult]:
        """处理单个批次：提交 → 并行轮询 → 获取结果

        Args:
            deep_mode: 若为 True，深度分析使用云端模型（qwen3.7-max）。
            lite_mode: 若为 True，辩论节点使用云端模型，数据收集保持本地。
        """
        symbols = [self._normalize_code(stock.code) for stock in batch]

        # 如果没有指定 analysis_date，使用今天
        if not analysis_date:
            from datetime import date
            analysis_date = date.today().strftime("%Y-%m-%d")

        # 提交批量分析
        use_cloud = deep_mode or lite_mode
        if deep_mode:
            logger.info("🔷 深度模式：深度分析使用云端模型 qwen3.7-max，快速分析使用本地模型")
        if lite_mode:
            logger.info("⚡ 轻量模式：辩论节点使用云端模型 qwen3.7-max，数据收集保持本地")
        payload = {
            "title": "Pipeline批量分析",
            "symbols": symbols,
            "parameters": {
                "market_type": "A股",
                "analysis_date": analysis_date,
                "research_depth": "深度",
                "selected_analysts": ["market", "fundamentals", "news", "social", "czsc","yangjia"],
                "include_sentiment": True,
                "include_risk": True,
                "language": "zh-CN",
                "quick_analysis_model": "local",
                "deep_analysis_model": "qwen3.7-max" if use_cloud else "local",
                "lite_mode": lite_mode,
            },
        }

        try:
            resp = requests.post(
                f"{self.base_url}/api/analysis/batch",
                headers=headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code != 200:
                logger.error("批次提交失败: HTTP %d", resp.status_code)
                return self._mark_batch_failed(batch, "批次提交失败")
        except Exception as e:
            logger.error("批次提交异常: %s", e)
            return self._mark_batch_failed(batch, f"提交异常: {e}")

        resp_data = resp.json()
        # API 返回结构: {"success": true, "data": {"task_ids": [...], "mapping": [...]}}
        data_obj = resp_data.get("data", resp_data)
        task_ids = data_obj.get("task_ids", [])

        if not task_ids:
            logger.error("批次提交未返回 task_ids, 响应: %s", resp_data)
            return self._mark_batch_failed(batch, "未返回 task_ids")

        logger.info("批次已提交，task_ids: %s", task_ids)

        # 并行轮询所有 task 的状态
        results: Dict[str, StockAnalysisResult] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = {
                executor.submit(self._poll_task, task_id, stock, headers, timeout_per_stock, deadline): stock
                for task_id, stock in zip(task_ids, batch)
            }
            for future in concurrent.futures.as_completed(futures):
                stock = futures[future]
                result = future.result()
                results[stock.code] = result

        return results

    def _poll_task(
        self,
        task_id: str,
        stock: StockFilterData,
        headers: Dict[str, str],
        timeout_per_stock: int,
        deadline=None,
    ) -> StockAnalysisResult:
        """轮询单个任务直到完成或超时。deadline 参数保留但不在轮询中检查，
        正在执行的任务会跑完（completed/failed/timeout），不会被 deadline 中断。

        TradingAgents 服务连续多次连接失败（ConnectionError）时判定服务不可用，
        立即快速失败，不再空转等待 timeout_per_stock。"""
        start_time = time.time()
        consecutive_401 = 0
        consecutive_conn_errors = 0

        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout_per_stock:
                logger.warning(
                    "股票 %s 分析超时（%.0fs）", stock.code, elapsed
                )
                return StockAnalysisResult(
                    code=stock.code,
                    status="timeout",
                    execution_time=elapsed,
                    error_message=f"分析超时（{timeout_per_stock}s）",
                )

            try:
                resp = requests.get(
                    f"{self.base_url}/api/analysis/tasks/{task_id}/status",
                    headers=headers,
                    timeout=10,
                )
                consecutive_conn_errors = 0  # 收到 HTTP 响应说明服务可达
                if resp.status_code == 401:
                    consecutive_401 += 1
                    if consecutive_401 >= 3:
                        # 连续 3 次 401，尝试重新登录
                        logger.warning(
                            "股票 %s 连续 %d 次 401，尝试刷新 Token...",
                            stock.code, consecutive_401
                        )
                        new_token = self._login()
                        if new_token:
                            headers["Authorization"] = f"Bearer {new_token}"
                            logger.info("Token 刷新成功，继续轮询")
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
                    logger.info(
                        "股票 %s 分析完成（%.0fs）", stock.code, elapsed
                    )
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

                # pending / processing → 继续轮询
                logger.info(
                    "股票 %s 状态: %s（%.0fs）", stock.code, status, elapsed
                )

            except requests.exceptions.ConnectionError as e:
                consecutive_conn_errors += 1
                if consecutive_conn_errors >= self._max_consecutive_conn_errors:
                    logger.error(
                        "任务 %s（股票 %s）连续 %d 次连接失败，判定 TradingAgents 服务不可用，停止轮询",
                        task_id, stock.code, consecutive_conn_errors,
                    )
                    return StockAnalysisResult(
                        code=stock.code,
                        status="failed",
                        execution_time=elapsed,
                        error_message=f"TradingAgents 服务不可用（连续 {consecutive_conn_errors} 次连接失败）",
                    )
                logger.warning(
                    "轮询任务 %s 连接失败（%d/%d）: %s",
                    task_id, consecutive_conn_errors,
                    self._max_consecutive_conn_errors, e,
                )
            except Exception as e:
                logger.warning("轮询任务 %s 异常: %s", task_id, e)
                consecutive_401 = 0
                consecutive_conn_errors = 0

            time.sleep(self._poll_interval)

    def _fetch_result(
        self,
        task_id: str,
        stock: StockFilterData,
        headers: Dict[str, str],
        elapsed: float,
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

            # 提取分析师报告
            reports = {}
            raw_reports = data.get("reports", {})
            if isinstance(raw_reports, dict):
                reports = raw_reports

            # 提取决策信息
            decision = data.get("decision", {})

            # confidence_score: 顶层有，decision 里也有，都是 0-1 小数
            raw_confidence = float(data.get("confidence_score", decision.get("confidence", 0)))
            # risk_score: 只在 decision 里有，顶层没有
            raw_risk = float(decision.get("risk_score", 0))

            # 转换为百分比（API 返回 0-1 小数）
            confidence_pct = raw_confidence * 100 if raw_confidence <= 1 else raw_confidence
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

    def _mark_batch_failed(
        self, batch: List[StockFilterData], error_msg: str
    ) -> Dict[str, StockAnalysisResult]:
        """将整个批次标记为失败"""
        return {
            stock.code: StockAnalysisResult(
                code=stock.code,
                status="failed",
                error_message=error_msg,
            )
            for stock in batch
        }
