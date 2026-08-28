"""
消费者模型并发调度器。

股票队列(生产者) + 多个模型 worker(消费者):
- 每只股票进入单一 FIFO 队列
- 每个 worker 独立抢任务,谁先抢到谁先跑,谁先完成谁的结果写报告
- 成功 → on_result;失败 → 重新入队(最多 max_retry 次)
- worker 连续 failure_threshold 次失败 → 本轮失效,不再抢任务
"""

import logging
import queue
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from pipeline.config import DispatchConfig, WorkerSpec
from pipeline.models import StockAnalysisResult, StockFilterData, WorkerOutcome

logger = logging.getLogger(__name__)


class StockDispatchQueue:
    def __init__(
        self,
        workers: List[WorkerSpec],
        dispatch_cfg: DispatchConfig,
        executor,
        deadline: Optional[datetime] = None,
    ):
        self._workers = {w.name: w for w in workers}
        self._cfg = dispatch_cfg
        self._executor = executor
        self._deadline = deadline

        self._queue: "queue.Queue[Tuple[StockFilterData, int]]" = queue.Queue()
        self._streak: Dict[str, int] = {name: 0 for name in self._workers}
        self._dead_workers: Set[str] = set()
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self._primary_by: Dict[str, str] = {}
        self._extras: List[WorkerOutcome] = []

    @property
    def dead_workers(self) -> List[str]:
        with self._lock:
            return sorted(self._dead_workers)

    @property
    def primary_by(self) -> Dict[str, str]:
        return dict(self._primary_by)

    @property
    def extras(self) -> List[WorkerOutcome]:
        return list(self._extras)

    def submit_all(self, stocks: List[StockFilterData]) -> None:
        for s in stocks:
            self._queue.put((s, 0))
        logger.info(
            "📦 入队 %d 只股票, worker %d 个: %s",
            len(stocks), len(self._workers), list(self._workers),
        )

    def run(
        self,
        on_result: Callable[[StockFilterData, StockAnalysisResult, str, int], None],
        on_extra: Callable[[WorkerOutcome], None],
        on_all_done: Callable[[], None],
    ) -> None:
        threads = []
        for worker in self._workers.values():
            t = threading.Thread(
                target=self._worker_loop,
                args=(worker, on_result, on_extra),
                daemon=True,
                name=f"worker-{worker.name}",
            )
            threads.append(t)
            t.start()

        while self._queue.unfinished_tasks > 0:
            if self._all_dead():
                self._drain_remaining(on_extra)
                break
            time.sleep(0.5)

        self._stop.set()
        for t in threads:
            t.join(timeout=5)
        on_all_done()

    def _worker_loop(self, worker: WorkerSpec, on_result, on_extra) -> None:
        token = self._executor.login()
        if not token:
            self._kill_worker(worker.name, "login failed")
            return
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        while not self._stop.is_set():
            try:
                stock, attempt = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            if worker.name in self._dead_workers:
                self._queue.put((stock, attempt))
                self._queue.task_done()
                return

            if self._deadline is not None and datetime.now() >= self._deadline:
                logger.info(
                    "⏰ 已过截止时间,跳过 %s/%s", stock.code, worker.name
                )
                on_extra(WorkerOutcome(
                    code=stock.code, worker_name=worker.name,
                    status="timeout", error_message="deadline passed",
                    attempt=attempt,
                ))
                self._queue.task_done()
                continue

            try:
                self._process(worker, stock, attempt, headers, on_result, on_extra)
            except Exception as e:
                logger.error(
                    "💥 worker[%s] 任务异常: %s", worker.name, e, exc_info=True
                )
                self._on_failure(
                    worker, stock, attempt, f"worker exception: {e}", on_extra
                )
            finally:
                self._queue.task_done()

    def _process(self, worker, stock, attempt, headers, on_result, on_extra) -> None:
        t0 = time.time()
        result = None
        err = ""
        try:
            task_id = self._executor.submit_one(stock, worker.model_name, headers)
            result = self._executor.poll_one(
                stock, task_id, headers, worker.timeout
            )
        except Exception as e:
            err = f"submit/poll 异常: {e}"

        elapsed = time.time() - t0

        if result and result.status == "completed":
            self._on_success(worker, stock, attempt, result, elapsed, on_result)
        else:
            self._on_failure(
                worker, stock, attempt,
                (result.error_message if result else err) or "unknown",
                on_extra,
            )

    def _on_success(self, worker, stock, attempt, result, elapsed, on_result) -> None:
        with self._lock:
            self._streak[worker.name] = 0
            self._primary_by[stock.code] = worker.name
        logger.info(
            "✅ [%s] %s 完成 (%.1fs)", worker.name, stock.code, elapsed
        )
        on_result(stock, result, worker.name, attempt)

    def _on_failure(self, worker, stock, attempt, err, on_extra) -> None:
        with self._lock:
            self._streak[worker.name] += 1
            streak = self._streak[worker.name]
            dead_now = (
                streak >= self._cfg.failure_threshold
                and worker.name not in self._dead_workers
            )
            if dead_now:
                self._dead_workers.add(worker.name)

        if dead_now:
            logger.error(
                "💀 [本轮失效] worker '%s' 连续失败 %d 次,本轮退出: %s",
                worker.name, streak, err,
            )
            on_extra(WorkerOutcome(
                code=stock.code, worker_name=worker.name,
                status="dead_skipped", error_message=f"worker dead: {err}",
                attempt=attempt,
            ))
            return

        if attempt >= self._cfg.max_retry:
            logger.warning(
                "❌ [永久失败] %s/%s attempt=%d: %s",
                stock.code, worker.name, attempt, err,
            )
            on_extra(WorkerOutcome(
                code=stock.code, worker_name=worker.name,
                status="failed", error_message=err, attempt=attempt,
            ))
            return

        logger.info(
            "🔁 [重试入队] %s/%s attempt=%d→%d (streak %d/%d): %s",
            stock.code, worker.name, attempt, attempt + 1,
            streak, self._cfg.failure_threshold, err,
        )
        self._queue.put((stock, attempt + 1))

    def _kill_worker(self, name: str, reason: str) -> None:
        with self._lock:
            if name not in self._dead_workers:
                self._dead_workers.add(name)
                logger.error("💀 [本轮失效] worker '%s': %s", name, reason)

    def _all_dead(self) -> bool:
        with self._lock:
            return len(self._dead_workers) == len(self._workers)

    def _drain_remaining(self, on_extra) -> None:
        remaining = 0
        while True:
            try:
                stock, attempt = self._queue.get_nowait()
            except queue.Empty:
                break
            remaining += 1
            on_extra(WorkerOutcome(
                code=stock.code, worker_name="<all_dead>",
                status="dead_skipped", error_message="all workers dead",
                attempt=attempt,
            ))
            self._queue.task_done()
        if remaining:
            logger.error("☠️ 所有 worker 失效,丢弃剩余 %d 只股票", remaining)
