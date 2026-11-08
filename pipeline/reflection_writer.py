"""把「情境 + 各角色的复盘文本」写进 5 个记忆集合。

为什么不复用 `TradingAgentsGraph.reflect_and_remember`：
那一条路径要用 LLM 逐角色生成「反思教训」（5 次 LLM ≈ 21 分钟/只）。
本方案改用确定性文本（结构化决策 + 真实收益 + 当时的原始论证），
只保留必要的那一步算力 —— 算向量。

为什么自己调 collection.add 而不是逐个 add_situations：
5 个角色的 situation 完全相同，`add_situations` 会各算一次向量。
实测手机算一次 6500 字要约 4 秒，5 次就是 20 秒，还徒增 4 倍手机负载。
所以这里只算一次向量，再复用到 5 个集合。
写入的字段形态与 `add_situations` 完全一致（同样的 documents/metadatas/ids 规则），
检索行为不受影响。
"""
import hashlib
import logging
import time
from typing import Dict, Optional, Set

from pipeline.reflection_text import ROLE_COLLECTIONS

logger = logging.getLogger(__name__)

# 锁冲突重试次数：退避 0.2/0.4/0.8/1.6s，合计约 3 秒，足够躲过瞬时锁
_ADD_ATTEMPTS = 5


def _fingerprint(text) -> str:
    """情境文本的指纹，用来判断「这条是不是已经写过了」。"""
    return hashlib.md5(str(text or "").encode("utf-8", "ignore")).hexdigest()


def _is_lock_error(exc) -> bool:
    text = str(exc).lower()
    return "lock" in text or "busy" in text


def _add_with_retry(collection, **kwargs):
    """写集合；遇到 sqlite 锁冲突就退避重试。

    ChromaDB 用的是 sqlite 的 **delete journal**（不是 WAL），跨进程读写会抢
    排他锁。分析进程随时可能在读记忆，一次 "database is locked" 就会让整条
    记忆被记失败 —— 而 fail_count 到 3 之后条目会被静默丢弃、记忆永久缺失。
    所以瞬时锁冲突必须扛住。
    """
    for attempt in range(_ADD_ATTEMPTS):
        try:
            collection.add(**kwargs)
            return
        except Exception as e:
            if attempt == _ADD_ATTEMPTS - 1 or not _is_lock_error(e):
                raise
            backoff = 0.2 * (2 ** attempt)
            logger.info("🔒 记忆库被占用，%.1fs 后重试（第 %d 次）", backoff, attempt + 1)
            time.sleep(backoff)


class MemoryWriter:
    """5 个原生记忆集合的写入器（不需要 graph、不需要 LLM 客户端）。"""

    def __init__(self, config: Optional[dict] = None, memories: Optional[Dict] = None):
        if memories is not None:
            self._memories: Dict[str, object] = dict(memories)
        else:
            # 延迟导入：dry-run 等场景不该被迫加载 TradingAgents-CN
            from tradingagents.agents.utils.memory import FinancialSituationMemory

            cfg = config or {"llm_provider": "localai"}
            self._memories = {
                role: FinancialSituationMemory(collection, cfg)
                for role, collection in ROLE_COLLECTIONS.items()
            }
            logger.info("📚 记忆写入器就绪: %s", ", ".join(sorted(self._memories)))
        self._seen: Dict[str, Set[str]] = self._load_seen()

    def _load_seen(self) -> Dict[str, Set[str]]:
        """把库里已有的情境指纹读进来，**按集合分别记**。

        为什么按集合分开：`write_all` 写 5 个集合时可能中途失败（前 2 个成功、
        第 3 个抛错）。若只在「5 个全写完」时才记指纹，重试会把已成功的集合再写一遍
        → 重复条目。分开记就能只补缺的那几个。

        为什么用文本指纹而不是改 id 方案：现存 582×5 条的 id 是自增计数，
        改成内容寻址 id 需要迁移老数据；指纹对老数据同样有效，零迁移。
        """
        seen: Dict[str, Set[str]] = {role: set() for role in self._memories}
        for role, mem in self._memories.items():
            getter = getattr(getattr(mem, "situation_collection", None), "get", None)
            if getter is None:
                continue
            try:
                docs = (getter(include=["documents"]) or {}).get("documents") or []
            except Exception as e:
                # 读不到就不去重：宁可可能重复（事后还能清），也不能因此永久漏写
                logger.warning("⚠️ 读 %s 已有记忆失败，该集合本轮不去重: %s", role, e)
                continue
            for d in docs:
                seen[role].add(_fingerprint(d))
        return seen

    def already_written(self, situation: str) -> bool:
        """这条情境是否所有集合都已写过 —— 是的话整条跳过，连 embedding 都不用算。"""
        if not self._seen:
            return False
        fp = _fingerprint(situation)
        return all(fp in s for s in self._seen.values())

    def write_all(self, situation: str, recommendations: Dict[str, str]) -> int:
        """把一条情境与各角色的复盘文本写进各自的集合，返回写入条数。

        某个角色的文本为空、或该集合里已经有这条情境，就跳过它，其余照写。
        写入失败会抛出，交给上层记 fail 并在下一轮重试 —— 不静默吞掉。
        """
        fp = _fingerprint(situation)
        pairs = [
            (role, rec)
            for role, rec in (recommendations or {}).items()
            if rec and role in self._memories and fp not in self._seen.get(role, set())
        ]
        if not pairs:
            logger.info("📭 没有可写入的复盘文本（为空或已写过），跳过")
            return 0

        # 同一段 situation 只向量化一次
        embedding = self._memories[pairs[0][0]].get_embedding(situation)
        if not embedding or not any(embedding):
            # memory.py 在向量端点不可达（Vulkan 掉设备、超长被拒等）时会
            # 「降级」返回零向量。零向量与任何文本的相似度都相同，写进去会把
            # 整个集合的检索搅坏，且无法事后区分。宁可抛出让 runner 记失败重试。
            raise RuntimeError("向量端点不可用（得到零向量/空向量），跳过本次写入")

        written = 0
        for role, rec in pairs:
            collection = self._memories[role].situation_collection
            _add_with_retry(
                collection,
                documents=[situation],
                metadatas=[{"recommendation": rec}],
                embeddings=[embedding],
                ids=[str(collection.count())],
            )
            # 只在真正写进去之后才记指纹：失败的不能算已写，否则重试会被跳过 → 永久漏写
            self._seen.setdefault(role, set()).add(fp)
            written += 1
        logger.info("✅ 已写入 %d 个记忆集合", written)
        return written


__all__ = ["MemoryWriter"]
