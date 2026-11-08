"""记忆写入器的测试。

写入路径不需要 graph、不需要 LLM，只需要「算一次向量 + 写 5 个集合」。
这里用假的 memory 对象把派发逻辑钉死，另外用真对象验证集合名与数据结构。
"""
import sys

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")
sys.path.insert(0, "/home/lima/workspace/stock/TradingAgents-CN")

from pipeline.reflection_text import ROLE_COLLECTIONS
from pipeline.reflection_writer import MemoryWriter


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.rows = []

    def count(self):
        return len(self.rows)

    def add(self, documents, metadatas, embeddings, ids):
        self.rows.append(
            {"documents": documents, "metadatas": metadatas, "embeddings": embeddings, "ids": ids}
        )

    def get(self, include=None):
        docs = []
        for r in self.rows:
            docs.extend(r["documents"])
        return {"documents": docs, "ids": []}


class FakeMemory:
    """记录自己被写了几次、写了什么。"""

    def __init__(self, name):
        self.situation_collection = FakeCollection(name)
        self.embed_calls = 0
        self.situations = []

    def get_embedding(self, text):
        self.embed_calls += 1
        self.situations.append(text)
        return [0.5] * 1024


def _writer():
    mems = {role: FakeMemory(coll) for role, coll in ROLE_COLLECTIONS.items()}
    return MemoryWriter(memories=mems), mems


def _recs(text="论证内容"):
    return {role: f"{role}的复盘｜{text}" for role in ROLE_COLLECTIONS}


class TestWriteAll:
    def test_写满五个集合并返回条数(self):
        w, mems = _writer()
        assert w.write_all("情境原文", _recs()) == 5
        for m in mems.values():
            assert len(m.situation_collection.rows) == 1

    def test_五个集合拿到的是同一段情境(self):
        w, mems = _writer()
        w.write_all("情境原文ABC", _recs())
        for m in mems.values():
            assert m.situation_collection.rows[0]["documents"] == ["情境原文ABC"]

    def test_recommendation原样写入metadata(self):
        w, mems = _writer()
        w.write_all("情境", _recs())
        for role, m in mems.items():
            meta = m.situation_collection.rows[0]["metadatas"][0]
            assert meta["recommendation"] == _recs()[role]

    def test_同一段情境只算一次向量(self):
        """手机算一次要 4 秒，5 次调用纯属浪费，也徒增手机负载。"""
        w, mems = _writer()
        w.write_all("情境原文", _recs())
        total = sum(m.embed_calls for m in mems.values())
        assert total == 1

    def test_空文本的角色被跳过(self):
        w, mems = _writer()
        recs = _recs()
        recs["多方研究员"] = ""
        assert w.write_all("情境", recs) == 4
        assert mems["多方研究员"].situation_collection.rows == []

    def test_全部为空时不写入也不抛(self):
        w, mems = _writer()
        assert w.write_all("情境", {}) == 0
        for m in mems.values():
            assert m.situation_collection.rows == []

    def test_未知角色被忽略(self):
        w, mems = _writer()
        assert w.write_all("情境", {"不存在的人": "x"}) == 0

    def test_写入id从集合当前条数起算(self):
        w, mems = _writer()
        w.write_all("情境一", _recs())
        w.write_all("情境二", _recs())
        ids = [r["ids"] for r in mems["交易员"].situation_collection.rows]
        assert ids == [["0"], ["1"]]

    def test_每次写入只带一条记录(self):
        w, mems = _writer()
        w.write_all("情境", _recs())
        row = mems["风控"].situation_collection.rows[0]
        assert len(row["documents"]) == 1
        assert len(row["metadatas"]) == 1
        assert len(row["embeddings"]) == 1
        assert len(row["ids"]) == 1


class TestWriteFailure:
    def test_单个集合写入失败会抛出以便重试(self):
        """失败要能冒泡到 runner，让它记 fail 并在下轮重试，不能静默吞掉。"""
        w, mems = _writer()

        class Boom(FakeCollection):
            def add(self, **kw):
                raise RuntimeError("ChromaDB 挂了")

        mems["交易员"].situation_collection = Boom("trader_memory")
        with pytest.raises(RuntimeError):
            w.write_all("情境", _recs())


class TestLockRetry:
    """ChromaDB 用 sqlite 的 delete journal 模式（不是 WAL），跨进程读写会抢排他锁。

    回填时分析进程正在读记忆，`database is locked` 一定会出现。若不重试，
    整条记忆被记失败；而 fail_count 到 3 之后条目会被静默丢弃、记忆永久缺失。
    """

    def _flaky(self, fail_times, message="database is locked"):
        class Flaky(FakeCollection):
            def __init__(self):
                super().__init__("trader_memory")
                self.calls = 0

            def add(self, **kw):
                self.calls += 1
                if self.calls <= fail_times:
                    raise RuntimeError(message)
                FakeCollection.add(self, **kw)

        return Flaky()

    def test_遇到锁冲突会退避重试直到成功(self, monkeypatch):
        import pipeline.reflection_writer as rw

        slept = []
        monkeypatch.setattr(rw.time, "sleep", slept.append)

        w, mems = _writer()
        flaky = self._flaky(fail_times=2)
        mems["交易员"].situation_collection = flaky

        assert w.write_all("情境", _recs()) == 5   # 5 个集合都写成功
        assert flaky.calls == 3                    # 失败 2 次 + 成功 1 次
        assert len(slept) == 2                     # 退避了 2 次
        assert slept == [0.2, 0.4]                 # 指数退避

    def test_非锁错误不重试立即抛出(self, monkeypatch):
        import pipeline.reflection_writer as rw

        monkeypatch.setattr(rw.time, "sleep", lambda s: pytest.fail("非锁错误不该重试"))

        w, mems = _writer()
        mems["交易员"].situation_collection = self._flaky(99, "向量维度不对")

        with pytest.raises(RuntimeError, match="向量维度不对"):
            w.write_all("情境", _recs())

    def test_锁冲突持续时重试到上限后抛出(self, monkeypatch):
        import pipeline.reflection_writer as rw

        monkeypatch.setattr(rw.time, "sleep", lambda s: None)

        w, mems = _writer()
        flaky = self._flaky(fail_times=99)
        mems["交易员"].situation_collection = flaky

        with pytest.raises(RuntimeError, match="locked"):
            w.write_all("情境", _recs())
        assert flaky.calls == rw._ADD_ATTEMPTS

    def test_busy也当作锁冲突重试(self, monkeypatch):
        import pipeline.reflection_writer as rw

        monkeypatch.setattr(rw.time, "sleep", lambda s: None)

        w, mems = _writer()
        flaky = self._flaky(fail_times=1, message="SQLITE_BUSY: database is busy")
        mems["交易员"].situation_collection = flaky

        assert w.write_all("情境", _recs()) == 5
        assert flaky.calls == 2


class TestDedupFingerprint:
    """已写过的情境不能被重复写入。

    `collect_backfillable` 会把**所有**算得出结果的决策重新登记（包括早就写好的），
    而成功的条目已经出队 —— 所以再跑一次 `--backfill` 就会把它们重新 embedding
    并写成**重复条目**（一次 22 秒的 embedding 也白烧）。
    用文本指纹去重：对现存的老数据同样有效（它们的 id 是自增计数，改 id 方案要迁移）。
    """

    def test_库里已有的情境被识别为已写(self):
        w, mems = _writer()
        w.write_all("情境A", _recs())

        w2 = MemoryWriter(memories=mems)      # 重新构造 = 模拟下一次运行
        assert w2.already_written("情境A") is True

    def test_没见过的情境不算已写(self):
        w, _ = _writer()
        w.write_all("情境A", _recs())
        assert w.already_written("情境B") is False

    def test_写入后立即进入指纹集(self):
        """同一轮里同一条被登记两次也不能写两遍。"""
        w, _ = _writer()
        assert w.already_written("情境A") is False
        w.write_all("情境A", _recs())
        assert w.already_written("情境A") is True

    def test_空库时什么都不算已写(self):
        w, _ = _writer()
        assert w.already_written("任何情境") is False

    def test_读已有记忆失败时不阻断构造(self):
        """读不到就宁可可能重复，也不能因此漏写（漏是永久性的，重复还能清）。"""
        class Boom(FakeCollection):
            def get(self, include=None):
                raise RuntimeError("ChromaDB 读不动")

        mems = {role: FakeMemory(coll) for role, coll in ROLE_COLLECTIONS.items()}
        mems["交易员"].situation_collection = Boom("trader_memory")
        w = MemoryWriter(memories=mems)
        assert w.already_written("情境A") is False

    def test_集合不支持get时跳过而不报错(self):
        class Bare:
            pass

        mems = {role: FakeMemory(coll) for role, coll in ROLE_COLLECTIONS.items()}
        mems["交易员"].situation_collection = Bare()
        w = MemoryWriter(memories=mems)
        assert w.already_written("情境A") is False

    def test_只写成功的才进指纹集(self):
        """写失败的情境不能算已写，否则重试时会被跳过 → 永久漏写。"""
        w, mems = _writer()

        class Boom(FakeCollection):
            def add(self, **kw):
                raise RuntimeError("ChromaDB 挂了")

        mems["交易员"].situation_collection = Boom("trader_memory")
        with pytest.raises(RuntimeError):
            w.write_all("情境A", _recs())
        assert w.already_written("情境A") is False


class TestRealMemoryShape:
    def test_五个集合名与原生一致(self):
        w, _ = _writer()
        names = {role: m.situation_collection.name for role, m in w._memories.items()}
        assert names == ROLE_COLLECTIONS

    def test_真实memory对象的写入结构与add_situations一致(self):
        """MemoryWriter 直接调 collection.add，语义必须和 add_situations 等价。"""
        from tradingagents.agents.utils.memory import FinancialSituationMemory

        mem = FinancialSituationMemory("probe_shape_memory", {"llm_provider": "localai"})
        mem.situation_collection.add(
            documents=["情境"],
            metadatas=[{"recommendation": "建议"}],
            embeddings=[[0.1] * 1024],
            ids=[str(mem.situation_collection.count())],
        )
        got = mem.situation_collection.get()
        assert got["documents"] == ["情境"]
        assert got["metadatas"] == [{"recommendation": "建议"}]

    def test_手机不可达时不写入垃圾而是抛出(self):
        """向量端点挂掉时 memory 内部会降级成零向量。

        零向量与任何文本的相似度都固定，写进去会把整个集合的检索搅坏，
        所以必须拦住 —— 抛出让 runner 记失败、下轮重试，比落一条垃圾强。
        """
        from tradingagents.agents.utils.memory import FinancialSituationMemory

        mem = FinancialSituationMemory("probe_degrade_memory", {"llm_provider": "localai"})
        w = MemoryWriter(memories={"多方研究员": mem})
        with pytest.raises(RuntimeError):
            w.write_all("情境", {"多方研究员": "复盘内容"})
        assert mem.situation_collection.count() == 0

    def test_零向量被拦截且一个集合都不写(self):
        w, mems = _writer()
        for m in mems.values():
            m.get_embedding = lambda text: [0.0] * 1024

        with pytest.raises(RuntimeError):
            w.write_all("情境", _recs())
        for m in mems.values():
            assert m.situation_collection.rows == []

    def test_向量退化但非全零时正常写入(self):
        """只有「全零」才是降级信号，极小值不算。"""
        w, mems = _writer()
        for m in mems.values():
            m.get_embedding = lambda text: [0.0] * 1023 + [1e-9]

        assert w.write_all("情境", _recs()) == 5

    def test_向量为空时也拦住(self):
        w, mems = _writer()
        for m in mems.values():
            m.get_embedding = lambda text: []

        with pytest.raises(RuntimeError):
            w.write_all("情境", _recs())
