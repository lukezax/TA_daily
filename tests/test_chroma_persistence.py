"""ChromaDB 持久化测试。

现状: chromadb_config.py 用 is_persistent=False + chromadb.Client(settings)，
是内存态；跨进程读不到数据。反思 worker 是独立进程，
写完记忆一退出就没了，第二天分析读不到任何东西。

这些用例锁定「必须落盘、且跨进程可见」这个要求。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TA_ROOT = Path("/home/lima/workspace/stock/TradingAgents-CN")


class TestPersistDir:
    def test_env可覆盖目录(self, monkeypatch, tmp_path):
        from tradingagents.agents.utils.chromadb_config import get_chroma_persist_dir

        monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "abc"))
        assert get_chroma_persist_dir() == str(tmp_path / "abc")

    def test_默认目录在项目data下(self, monkeypatch):
        from tradingagents.agents.utils.chromadb_config import get_chroma_persist_dir

        monkeypatch.delenv("CHROMA_PERSIST_DIR", raising=False)
        p = Path(get_chroma_persist_dir())
        assert p.is_absolute()
        assert "chroma" in p.name.lower()
        assert str(TA_ROOT) in str(p), "默认目录应落在 TradingAgents-CN 下"

    def test_env为空字符串时回退默认(self, monkeypatch):
        from tradingagents.agents.utils.chromadb_config import get_chroma_persist_dir

        monkeypatch.setenv("CHROMA_PERSIST_DIR", "")
        p = Path(get_chroma_persist_dir())
        assert str(TA_ROOT) in str(p)


class TestClientIsPersistent:
    def test_两次创建互相读得到(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "d"))
        from tradingagents.agents.utils.chromadb_config import get_optimal_chromadb_client

        c1 = get_optimal_chromadb_client()
        c1.get_or_create_collection("probe_mem").add(
            ids=["1"], embeddings=[[0.5] * 1024], documents=["记忆内容"]
        )

        c2 = get_optimal_chromadb_client()
        assert c2.get_collection("probe_mem").count() == 1

    def test_数据真的落盘(self, monkeypatch, tmp_path):
        d = tmp_path / "d"
        monkeypatch.setenv("CHROMA_PERSIST_DIR", str(d))
        from tradingagents.agents.utils.chromadb_config import get_optimal_chromadb_client

        c = get_optimal_chromadb_client()
        c.get_or_create_collection("disk_mem").add(
            ids=["1"], embeddings=[[0.5] * 1024], documents=["x"]
        )
        assert (d / "chroma.sqlite3").exists(), "应生成 chroma.sqlite3 落盘文件"

    def test_目录会被自动创建(self, monkeypatch, tmp_path):
        d = tmp_path / "nested" / "deep"
        monkeypatch.setenv("CHROMA_PERSIST_DIR", str(d))
        from tradingagents.agents.utils.chromadb_config import get_optimal_chromadb_client

        get_optimal_chromadb_client()
        assert d.exists()


class TestCrossProcessPersistence:
    """最关键的一条：写入方和读取方是不同进程。

    反思 worker 写、明天 pipeline 读 —— 必须能读到。
    """

    def test_独立进程写入后另一个进程能读到(self, tmp_path):
        d = str(tmp_path / "chroma")
        env = dict(os.environ, CHROMA_PERSIST_DIR=d)

        writer = (
            f"import sys; sys.path.insert(0, r'{TA_ROOT}');"
            "from tradingagents.agents.utils.chromadb_config import get_optimal_chromadb_client;"
            "c = get_optimal_chromadb_client();"
            "col = c.get_or_create_collection('cross_mem');"
            "col.add(ids=['k1'], embeddings=[[0.25]*1024], documents=['昨天的决策：买入']);"
            "print('WROTE', col.count())"
        )
        w = subprocess.run(
            [sys.executable, "-c", writer], env=env, capture_output=True, text=True, timeout=180
        )
        assert "WROTE 1" in w.stdout, f"写入进程失败: {w.stderr[-600:]}"

        reader = (
            f"import sys; sys.path.insert(0, r'{TA_ROOT}');"
            "from tradingagents.agents.utils.chromadb_config import get_optimal_chromadb_client;"
            "c = get_optimal_chromadb_client();"
            "col = c.get_collection('cross_mem');"
            "print('READ', col.count(), col.get()['documents'])"
        )
        r = subprocess.run(
            [sys.executable, "-c", reader], env=env, capture_output=True, text=True, timeout=180
        )
        assert "READ 1" in r.stdout, f"读取进程看不到数据: {r.stderr[-600:]}"
        assert "昨天的决策：买入" in r.stdout
