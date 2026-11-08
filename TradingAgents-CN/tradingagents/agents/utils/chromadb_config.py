"""ChromaDB 统一配置模块。

记忆必须落盘：反思 worker 是独立进程，它写下的记忆要能被
第二天的分析进程读到。原先这里是 is_persistent=False 的内存态，
跨进程读不到，反思机制会整个空转。

所以客户端统一走 PersistentClient，目录可用 CHROMA_PERSIST_DIR 覆盖。
"""
import logging
import os
import platform
from pathlib import Path

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_PERSIST_DIRNAME = "chroma_db"
# chromadb_config.py -> utils -> agents -> tradingagents -> TradingAgents-CN
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def is_windows_11() -> bool:
    """
    检测是否为 Windows 11

    Returns:
        bool: 如果是 Windows 11 返回 True，否则返回 False
    """
    if platform.system() != "Windows":
        return False

    # Windows 11 的版本号通常是 10.0.22000 或更高
    version = platform.version()
    try:
        # 提取版本号，格式通常是 "10.0.26100"
        version_parts = version.split('.')
        if len(version_parts) >= 3:
            build_number = int(version_parts[2])
            # Windows 11 的构建号从 22000 开始
            return build_number >= 22000
    except (ValueError, IndexError):
        pass

    return False


def get_chroma_persist_dir() -> str:
    """ChromaDB 落盘目录。CHROMA_PERSIST_DIR 优先，否则落在项目 data/ 下。"""
    configured = os.getenv("CHROMA_PERSIST_DIR", "").strip()
    if configured:
        return configured
    return str(_PROJECT_ROOT / "data" / DEFAULT_PERSIST_DIRNAME)


def get_optimal_chromadb_client():
    """返回持久化的 ChromaDB 客户端。

    初始化失败时降级为内存态并显著告警，保证分析流程不中断；
    但降级状态下记忆重启即丢。
    """
    path = get_chroma_persist_dir()
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=path,
            settings=Settings(allow_reset=True, anonymized_telemetry=False),
        )
        system = platform.system()
        logger.info(f"📚 [ChromaDB] 持久化客户端就绪: {path} ({system})")
        return client
    except Exception as e:
        logger.error(f"❌ [ChromaDB] 持久化初始化失败({path}): {e}")
        logger.warning("⚠️ [ChromaDB] 降级为内存态 —— 本进程内可用，重启后记忆全部丢失")
        return chromadb.Client(Settings(allow_reset=True, anonymized_telemetry=False))


# 导出配置
__all__ = [
    'get_optimal_chromadb_client',
    'get_chroma_persist_dir',
    'is_windows_11',
]
