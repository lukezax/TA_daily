"""embedding 结果缓存的测试。

为什么要缓存：换成远程 embedding 服务后**单次约 22 秒**，而一次分析里有 5 个
agent 各调一次 `get_memories`。实测这四个（bull / bear / trader / research_manager）
拼出来的 `curr_situation` 文本**逐字相同**（四份报告 + 缠论段），只有 risk_manager
少缠论那段 —— 也就是 5 次调用里只有 2 种文本。不缓存就是每股白烧 3×22≈66 秒。

缓存必须守住的两条底线：
1. **零向量不进缓存** —— `get_embedding` 在服务出错时「降级」返回 `[0.0]*1024`，
   一旦缓存住，一次瞬时故障就把这段文本永久钉死成垃圾向量。
2. **键里含端点与模型名** —— 换了 embedding 服务（手机→远程）后，旧向量必须失效。
"""
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")
sys.path.insert(0, "/home/lima/workspace/stock/TradingAgents-CN")

from tradingagents.agents.utils import memory as memory_mod
from tradingagents.agents.utils.memory import FinancialSituationMemory


class FakeEmbeddings:
    def __init__(self, outer):
        self.outer = outer

    def create(self, model=None, input=None):
        self.outer.calls.append(input)
        if self.outer.fail_times > 0:
            self.outer.fail_times -= 1
            raise RuntimeError("Connection error.")
        vec = self.outer.next_vector()
        return type("R", (), {"data": [type("D", (), {"embedding": vec})]})()


class FakeClient:
    """记录被调了几次、每次的文本。默认返回可区分的非零向量。"""

    def __init__(self, base_url="http://fake/v1", zero=False, tag=0.0):
        self.calls = []
        self.fail_times = 0
        self.base_url = base_url
        self.zero = zero
        self.tag = tag          # 让不同 client 的向量可区分（验证跨端点不串用）
        self.embeddings = FakeEmbeddings(self)
        self._n = 0

    def next_vector(self):
        if self.zero:
            return [0.0] * 1024
        self._n += 1
        return [self.tag + float(self._n)] * 1024


@pytest.fixture
def mem():
    m = FinancialSituationMemory("probe_cache_memory", {"llm_provider": "localai"})
    m.client = FakeClient()
    m.embedding = "bge-m3"
    yield m
    memory_mod.clear_embedding_cache()


def _mem_with(client):
    m = FinancialSituationMemory("probe_cache_memory", {"llm_provider": "localai"})
    m.client = client
    m.embedding = "bge-m3"
    return m


class TestCacheHit:
    def test_同一文本第二次不再请求(self, mem):
        a = mem.get_embedding("同一份情境文本")
        b = mem.get_embedding("同一份情境文本")
        assert len(mem.client.calls) == 1
        assert a == b

    def test_不同文本各自请求(self, mem):
        mem.get_embedding("情境A")
        mem.get_embedding("情境B")
        assert len(mem.client.calls) == 2

    def test_五个agent里四种同文本只算一次(self, mem):
        """这就是缓存要解决的实际场景。"""
        same = "四份报告+缠论段"
        for _ in range(4):                      # bull/bear/trader/research_manager
            mem.get_embedding(same)
        mem.get_embedding("四份报告，没有缠论段")   # risk_manager
        assert len(mem.client.calls) == 2

    def test_跨实例共享缓存(self):
        """5 个 agent 各有各的 memory 实例，缓存必须是模块级才省得下来。"""
        client = FakeClient()
        m1, m2 = _mem_with(client), _mem_with(client)
        v1 = m1.get_embedding("共享文本")
        v2 = m2.get_embedding("共享文本")
        assert len(client.calls) == 1
        assert v1 == v2
        memory_mod.clear_embedding_cache()

    def test_返回的是副本_改返回值不污染缓存(self, mem):
        a = mem.get_embedding("情境C")
        a[0] = 999.0
        b = mem.get_embedding("情境C")
        assert b[0] != 999.0
        assert len(mem.client.calls) == 1


class TestZeroVectorNotCached:
    def test_服务出错返回的零向量不进缓存(self):
        client = FakeClient(zero=True)
        m = _mem_with(client)
        assert any(m.get_embedding("会失败的文本")) is False
        assert len(client.calls) == 1

        client.zero = False                      # 服务恢复了
        v = m.get_embedding("会失败的文本")
        assert any(v) is True                    # 必须重新算，不能吃缓存里的零向量
        assert len(client.calls) == 2
        memory_mod.clear_embedding_cache()

    def test_异常降级后恢复也能重算(self):
        client = FakeClient()
        client.fail_times = 1
        m = _mem_with(client)
        m.get_embedding("第一次会抛异常的文本")     # 内部吞掉异常 → 零向量
        v = m.get_embedding("第一次会抛异常的文本")
        assert any(v) is True
        memory_mod.clear_embedding_cache()


class TestKeyIsolation:
    def test_换端点后旧向量失效(self):
        c1 = FakeClient(base_url="http://phone:8222/v1", tag=0.0)
        c2 = FakeClient(base_url="http://localhost:18223/v1", tag=100.0)
        m1, m2 = _mem_with(c1), _mem_with(c2)
        v1 = m1.get_embedding("同一段文本")
        v2 = m2.get_embedding("同一段文本")
        assert len(c1.calls) == 1 and len(c2.calls) == 1
        assert v1 != v2                          # 两台服务器算出来的向量不该混用
        memory_mod.clear_embedding_cache()

    def test_换模型名后旧向量失效(self):
        c = FakeClient()
        m = _mem_with(c)
        m.embedding = "bge-m3"
        m.get_embedding("同一段文本")
        m.embedding = "nomic-embed-text"
        m.get_embedding("同一段文本")
        assert len(c.calls) == 2
        memory_mod.clear_embedding_cache()


class TestCacheBound:
    def test_超过上限淘汰最旧的(self, monkeypatch, mem):
        monkeypatch.setenv("EMBEDDING_CACHE_SIZE", "2")
        mem.get_embedding("文本1")
        mem.get_embedding("文本2")
        mem.get_embedding("文本3")               # 挤掉「文本1」
        assert len(mem.client.calls) == 3

        mem.get_embedding("文本1")               # 已被淘汰 → 重新算
        assert len(mem.client.calls) == 4
        mem.get_embedding("文本3")               # 还在 → 命中
        assert len(mem.client.calls) == 4

    def test_上限设为0等于关闭缓存(self, monkeypatch, mem):
        monkeypatch.setenv("EMBEDDING_CACHE_SIZE", "0")
        mem.get_embedding("文本X")
        mem.get_embedding("文本X")
        assert len(mem.client.calls) == 2

    def test_非法上限退回默认(self, monkeypatch, mem):
        monkeypatch.setenv("EMBEDDING_CACHE_SIZE", "不是数字")
        assert memory_mod._embedding_cache_size() == 8


class TestDegradedInputs:
    def test_空文本不缓存也不报错(self, mem):
        assert mem.get_embedding("") == [0.0] * 1024
        assert mem.get_embedding(None) == [0.0] * 1024
        assert mem.client.calls == []

    def test_非字符串输入不被缓存(self, mem):
        mem.get_embedding(12345)
        mem.get_embedding(12345)
        assert len(mem.client.calls) == 0

    def test_clear能清空(self, mem):
        mem.get_embedding("文本Y")
        memory_mod.clear_embedding_cache()
        mem.get_embedding("文本Y")
        assert len(mem.client.calls) == 2
