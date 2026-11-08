"""get_memories 在记忆库为空时不该先算 embedding。

现状 memory.py:652 先算 query_embedding（打一次手机 embedding，长文本约 7.5 秒），
然后才在 660 行检查 collection_count == 0 并丢弃。

5 个 agent 节点都会调 get_memories，所以库为空时每只股白白消耗 5+ 次请求。
"""
import sys
import uuid

import pytest

sys.path.insert(0, "/home/lima/workspace/stock/TradingAgents-CN")

from tradingagents.agents.utils.memory import FinancialSituationMemory


@pytest.fixture
def mem():
    """每次用全新集合名，保证初始为空。"""
    return FinancialSituationMemory(f"t_{uuid.uuid4().hex[:12]}", {"llm_provider": "openai"})


class TestEmptyLibraryShortCircuit:
    def test_库为空时不调用get_embedding(self, mem):
        calls = []

        def spy(text):
            calls.append(text)
            return [0.1] * 1024

        mem.get_embedding = spy
        assert mem.get_memories("今天的情况") == []
        assert calls == [], "库为空，不该白白打一次 embedding 请求"

    def test_库为空返回空列表(self, mem):
        assert mem.get_memories("今天的情况") == []

    def test_空库查询不受embedding失败影响(self, mem):
        """库为空时即使 embedding 端点不可用，也应正常返回空列表"""

        def boom(text):
            raise RuntimeError("手机崩了")

        mem.get_embedding = boom
        assert mem.get_memories("今天的情况") == []

    def test_库非空时会调用get_embedding(self, mem):
        mem.situation_collection.add(
            ids=["m1"],
            embeddings=[[0.1] * 1024],
            documents=["昨天的决策"],
            metadatas=[{"recommendation": "买入"}],
        )
        calls = []

        def spy(text):
            calls.append(text)
            return [0.1] * 1024

        mem.get_embedding = spy
        result = mem.get_memories("今天的情况")
        assert len(calls) == 1, "库非空时必须正常查询"
        assert len(result) == 1
        assert result[0]["recommendation"] == "买入"
        assert result[0]["situation"] == "昨天的决策"
