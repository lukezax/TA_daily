"""调度器里的「记忆写入」钩子测试。

要保证两件事：
1. 开关关掉时绝不能去连 ChromaDB（否则没准备好的环境会被拖挂）
2. 回填与「明天是否交易日」解耦 —— 它处理的是历史决策，
   周五/节假日夜里也该把队列清干净，否则积压到下周
"""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")

from pipeline.orchestrator import PipelineScheduler


class FakeScheduler(PipelineScheduler):
    """绕开真实 orchestrator 的构造（它要连 API）。"""

    def __init__(self, enabled=True):
        self.config = SimpleNamespace(reflection_enabled=enabled)
        self.orchestrator = MagicMock()

    def _is_date_trading_day(self, d):
        return False


class TestRunReflection:
    def test_未启用时不构造写入器(self):
        s = FakeScheduler(enabled=False)
        with patch("pipeline.reflection_runner.ReflectionRunner") as R:
            s._run_reflection()
        R.assert_not_called()

    def test_启用时跑一轮(self):
        s = FakeScheduler(enabled=True)
        with patch("pipeline.reflection_runner.ReflectionRunner") as R, \
             patch("pipeline.run_reflection._build_writer", return_value="W"):
            R.return_value.run_once.return_value = 3
            s._run_reflection()
        R.assert_called_once()
        assert R.call_args.kwargs["writer"] is not None
        R.return_value.run_once.assert_called_once()

    def test_执行期异常不抛出(self):
        """写入器构造失败 / ChromaDB 连不上，都不能把整条夜间流水线带崩。"""
        s = FakeScheduler(enabled=True)
        with patch("pipeline.reflection_runner.ReflectionRunner") as R, \
             patch("pipeline.run_reflection._build_writer", return_value="W"):
            R.return_value.run_once.side_effect = RuntimeError("ChromaDB 挂了")
            s._run_reflection()  # 不抛即通过

    def test_缺配置字段时按未启用来处理(self):
        class Bare(PipelineScheduler):
            def __init__(self):
                self.config = SimpleNamespace()
                self.orchestrator = MagicMock()

        with patch("pipeline.reflection_runner.ReflectionRunner") as R:
            Bare()._run_reflection()
        R.assert_not_called()


class TestPipelineOrdering:
    def test_非交易日也会先回填记忆(self):
        """回填不依赖「明天是交易日」：它消费的是旧决策。"""
        s = FakeScheduler(enabled=True)
        called = []
        s._run_reflection = lambda: called.append(1)

        s._run_pipeline()

        assert called == [1]
        assert not s.orchestrator.run.called  # 非交易日不跑分析

    def test_回填在分析之前发生(self):
        """先回填再分析：避免写入与「分析时读记忆」跨进程撞在一起。"""
        s = FakeScheduler(enabled=True)
        order = []
        s._run_reflection = lambda: order.append("reflection")
        s.orchestrator.run.side_effect = lambda **kw: order.append("pipeline") or MagicMock()
        s._is_date_trading_day = lambda d: True

        s._run_pipeline()

        assert order == ["reflection", "pipeline"]
