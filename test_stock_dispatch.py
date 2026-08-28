"""
StockDispatchQueue 消费者模型测试。
对照 模型并发调度方案.md 第 12 节 TDD 验收标准 T1-T8。
"""

import unittest

from pipeline.config import DispatchConfig, WorkerSpec
from pipeline.models import StockAnalysisResult, StockFilterData
from pipeline.stock_dispatch import StockDispatchQueue


def make_stock(code):
    return StockFilterData(code=code, name=f"股票{code}", exchange="SH", result=True)


def ok_result(code):
    return StockAnalysisResult(code=code, status="completed", recommendation="买入")


def fail_result(code, msg="boom"):
    return StockAnalysisResult(code=code, status="failed", error_message=msg)


class FakeExecutor:
    """可配置行为的假 executor。handler(stock, model_name) -> StockAnalysisResult。"""

    def __init__(self, handler):
        self._handler = handler
        self._deadline = None
        self.submit_calls = []

    def login(self):
        return "fake-token"

    def submit_one(self, stock, model_name, headers):
        self.submit_calls.append((stock.code, model_name))
        return f"task-{stock.code}-{model_name}"

    def poll_one(self, stock, task_id, headers, timeout):
        model_name = task_id.rsplit("-", 1)[1]
        return self._handler(stock, model_name)


def run_dispatch(workers, cfg, stocks, handler):
    executor = FakeExecutor(handler)
    queue = StockDispatchQueue(workers, cfg, executor)
    queue.submit_all(stocks)
    results = {}
    extras = []
    queue.run(
        on_result=lambda s, r, w, a: results.__setitem__(s.code, r),
        on_extra=lambda o: extras.append(o),
        on_all_done=lambda: None,
    )
    return queue, executor, results, extras


class TestSubmitAll(unittest.TestCase):
    def test_t1_queue_size_equals_stock_count(self):
        workers = [WorkerSpec("local", "m1"), WorkerSpec("cloud", "m2")]
        queue = StockDispatchQueue(workers, DispatchConfig(), FakeExecutor(lambda s, m: ok_result(s.code)))
        queue.submit_all([make_stock(c) for c in ["600519.SH", "000001.SZ", "300750.SZ"]])
        self.assertEqual(queue._queue.qsize(), 3)


class TestSuccess(unittest.TestCase):
    def test_t2_single_worker_single_stock_success(self):
        queue, executor, results, extras = run_dispatch(
            [WorkerSpec("local", "m1")], DispatchConfig(), [make_stock("600519.SH")],
            lambda s, m: ok_result(s.code),
        )
        self.assertEqual(results["600519.SH"].status, "completed")
        self.assertEqual(results["600519.SH"].recommendation, "买入")
        self.assertEqual(executor.submit_calls, [("600519.SH", "m1")])


class TestRetry(unittest.TestCase):
    def test_t3_fail_once_then_success(self):
        state = {"count": 0}

        def handler(stock, model):
            state["count"] += 1
            if state["count"] == 1:
                return fail_result(stock.code)
            return ok_result(stock.code)

        queue, executor, results, extras = run_dispatch(
            [WorkerSpec("local", "m1")], DispatchConfig(max_retry=1, failure_threshold=3),
            [make_stock("600519.SH")], handler,
        )
        self.assertEqual(results["600519.SH"].status, "completed")
        self.assertEqual(len(executor.submit_calls), 2)
        self.assertEqual([e.status for e in extras], [])

    def test_t4_permanent_fail_after_max_retry(self):
        queue, executor, results, extras = run_dispatch(
            [WorkerSpec("local", "m1")], DispatchConfig(max_retry=1, failure_threshold=3),
            [make_stock("600519.SH")], lambda s, m: fail_result(s.code),
        )
        self.assertEqual(len(results), 0)
        self.assertEqual(len(executor.submit_calls), 2)
        self.assertEqual([e.status for e in extras], ["failed"])


class TestDeadWorker(unittest.TestCase):
    def test_t5_worker_dead_after_threshold(self):
        queue, executor, results, extras = run_dispatch(
            [WorkerSpec("local", "m1")], DispatchConfig(max_retry=1, failure_threshold=3),
            [make_stock(c) for c in ["600519.SH", "000001.SZ", "300750.SZ"]],
            lambda s, m: fail_result(s.code),
        )
        self.assertEqual(len(results), 0)
        self.assertEqual(queue.dead_workers, ["local"])
        self.assertIn("dead_skipped", [e.status for e in extras])

    def test_t6_all_dead_drains_without_deadlock(self):
        workers = [WorkerSpec("local", "m1"), WorkerSpec("cloud", "m2")]
        queue, executor, results, extras = run_dispatch(
            workers, DispatchConfig(max_retry=1, failure_threshold=3),
            [make_stock(c) for c in ["600519.SH", "000001.SZ", "300750.SZ", "000858.SZ"]],
            lambda s, m: fail_result(s.code),
        )
        self.assertEqual(len(results), 0)
        self.assertEqual(sorted(queue.dead_workers), ["cloud", "local"])


class TestConcurrentConsumers(unittest.TestCase):
    def test_two_workers_share_single_queue(self):
        # 两只 worker 抢任务:每只股只被一个 worker 持有到完成,无重复消费
        state = {"count": 0}

        def handler(stock, model):
            state["count"] += 1
            return ok_result(stock.code)

        queue, executor, results, extras = run_dispatch(
            [WorkerSpec("local", "m1"), WorkerSpec("cloud", "m2")],
            DispatchConfig(),
            [make_stock(c) for c in ["600519.SH", "000001.SZ", "300750.SZ", "000858.SZ"]],
            handler,
        )
        # 4 只股各完成一次,无重复消费(总提交数 = 股数)
        self.assertEqual(len(results), 4)
        self.assertEqual(state["count"], 4)
        self.assertEqual(len(executor.submit_calls), 4)


if __name__ == "__main__":
    unittest.main()
