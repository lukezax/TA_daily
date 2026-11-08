"""CLI 入口的参数测试。"""
import subprocess
import sys

ROOT = "/home/lima/workspace/stock"


def _run(args):
    return subprocess.run(
        [sys.executable, "-m", "pipeline.run_reflection", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


class TestCli:
    def test_试运行模式可用(self):
        r = _run(["--dry-run"])
        assert r.returncode == 0, r.stderr[-500:]

    def test_试运行输出待处理统计(self):
        r = _run(["--dry-run"])
        combined = r.stdout + r.stderr
        assert "待处理" in combined
        assert "试运行" in combined

    def test_帮助可打印(self):
        r = _run(["--help"])
        assert r.returncode == 0
        assert "--dry-run" in r.stdout

    def test_试运行不修改队列(self):
        from pymongo import MongoClient

        coll = MongoClient("mongodb://localhost:27017")["tradingagentscn"]["reflection_pending"]
        before = coll.count_documents({})
        _run(["--dry-run"])
        assert coll.count_documents({}) == before

    def test_帮助里有retry_all(self):
        r = _run(["--help"])
        assert "--retry-all" in r.stdout


class TestRetryAllWiring:
    """--retry-all 必须在跑之前把失败计数归零。

    用假 runner 在进程内测接线，不碰真实队列、不建真实写入器。
    """

    class FakeStore:
        def __init__(self):
            self.resets = 0

        def reset_failures(self):
            self.resets += 1
            return 7

        def all_pending(self):
            return []

    class FakeRunner:
        def __init__(self, **kwargs):
            self.store = TestRetryAllWiring.FakeStore()
            self.kwargs = kwargs

        def run_once(self):
            return 0

    def _spy(self, monkeypatch, argv):
        """跑一次 main()，返回 reset_failures 被调了几次。"""
        import pipeline.run_reflection as rr

        calls = []
        outer = self

        class Spy(outer.FakeRunner):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.store.reset_failures = lambda: calls.append(1) or 0

        monkeypatch.setattr(rr, "ReflectionRunner", Spy)
        monkeypatch.setattr(sys, "argv", ["run_reflection", *argv])
        rr.main()
        return calls

    def test_不带retry_all时不动计数(self, monkeypatch):
        assert self._spy(monkeypatch, []) == []

    def test_带retry_all时确实归零(self, monkeypatch):
        assert self._spy(monkeypatch, ["--retry-all"]) == [1]

    def test_试运行即使带retry_all也不归零(self, monkeypatch):
        """试运行必须保持只读 —— 否则「看一眼」就会改掉重试预算。"""
        assert self._spy(monkeypatch, ["--dry-run", "--retry-all"]) == []