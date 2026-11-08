"""pytest 全局配置。

测试绝不能碰生产环境的任何持久化状态：
- ChromaDB 改为持久化后必须写到临时目录，否则污染生产记忆库
- TradingAgents-CN 导入时会配置日志写 ./logs/，必须重定向
- 测试用的 PendingReflectionStore 会在真实 Mongo 里留集合，收尾清掉
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, "/home/lima/workspace/stock")
sys.path.insert(0, "/home/lima/workspace/stock/TradingAgents-CN")

# ChromaDB 落盘到临时目录，绝不碰生产记忆库
_TEST_CHROMA_DIR = tempfile.mkdtemp(prefix="chroma_pytest_")
os.environ["CHROMA_PERSIST_DIR"] = _TEST_CHROMA_DIR

# TradingAgents-CN 的 logging_manager 认这个变量（默认 ./logs）。
# 不重定向的话，pytest 会把 <MagicMock>、模拟的异常栈写进生产日志，
# 事后读日志排查真实问题时会被带偏 —— 这个坑真踩过。
_TEST_LOG_DIR = tempfile.mkdtemp(prefix="logs_pytest_")
os.environ["TRADINGAGENTS_LOG_DIR"] = _TEST_LOG_DIR

# 指向 discard 端口：万一有代码真的发起 embedding 请求，立刻失败而不是挂住
os.environ.setdefault("EMBEDDING_BASE_URL", "http://127.0.0.1:9/v1")
os.environ.setdefault("EMBEDDING_MODEL", "bge-m3")


@pytest.fixture(autouse=True)
def _reset_chroma_singleton():
    """每个用例前重建 ChromaDBManager 单例，避免集合缓存跨用例串味。"""
    try:
        from tradingagents.agents.utils.memory import ChromaDBManager
    except Exception:
        yield
        return

    ChromaDBManager._instance = None
    ChromaDBManager._collections = {}
    yield
    ChromaDBManager._instance = None
    ChromaDBManager._collections = {}


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_collections():
    """收尾清掉测试在真实 Mongo 里留下的 test_* 集合。

    测试只 clear() 集合里的文档，空集合本身会一直留着。
    """
    yield
    try:
        from pymongo import MongoClient

        db = MongoClient("mongodb://localhost:27017")["tradingagentscn"]
        for name in db.list_collection_names():
            if name.startswith("test_"):
                db.drop_collection(name)
    except Exception:
        pass

