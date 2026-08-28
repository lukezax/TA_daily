"""Tavily 搜索 - 为策略分析提供外部信息源"""

import logging
from typing import List, Dict

from strategy_researcher.config import RESEARCHER_CONFIG

logger = logging.getLogger("strategy_researcher.tavily")


class TavilyClient:
    """Tavily 搜索客户端 - 信息源工具"""

    def __init__(self):
        self.api_key = RESEARCHER_CONFIG["tavily_api_key"]
        self.max_results = RESEARCHER_CONFIG["tavily_max_results"]
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from tavily import TavilyClient as _TC
                self._client = _TC(api_key=self.api_key)
            except ImportError:
                logger.warning("tavily-python 未安装，搜索功能不可用")
                return None
            except Exception as e:
                logger.warning("Tavily 初始化失败: %s", e)
                return None
        return self._client

    def search(self, query: str) -> List[Dict]:
        """搜索并返回结果摘要"""
        client = self._get_client()
        if not client:
            return []

        try:
            response = client.search(
                query=query,
                max_results=self.max_results,
                search_depth="basic",
            )
            results = []
            for item in response.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", "")[:500],
                })
            logger.info("Tavily 搜索 '%s': %d 条结果", query, len(results))
            return results
        except Exception as e:
            logger.warning("Tavily 搜索失败: %s", e)
            return []

    def get_market_context(self) -> str:
        """搜索当前A股市场环境"""
        results = self.search("A股市场 近期走势 风格轮动 2026")
        if not results:
            return "（无法获取市场信息）"
        return "\n\n".join(f"**{r['title']}**\n{r['content']}" for r in results)

    def get_strategy_knowledge(self, topic: str) -> str:
        """搜索特定策略/指标的知识"""
        results = self.search(f"{topic} 量化策略 A股 优化")
        if not results:
            return "（无搜索结果）"
        return "\n\n".join(f"**{r['title']}**\n{r['content']}" for r in results)
