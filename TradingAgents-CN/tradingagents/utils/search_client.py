"""
多源搜索客户端 - 支持 BochaAI / Exa / SerpAPI / Tavily 轮换

优先级：BochaAI(免费) → Exa → SerpAPI → Tavily(兜底)
当一个源失败或额度用尽时自动切换到下一个
"""

import os
import logging
import time
import json
from typing import List, Dict, Optional
from datetime import date
from pathlib import Path

logger = logging.getLogger("tradingagents.search_client")

# 额度追踪文件
_USAGE_FILE = Path(__file__).parent.parent.parent / "logs" / "search_usage.json"


class SearchResult:
    """统一的搜索结果格式"""

    def __init__(self, title: str, url: str, content: str, source: str):
        self.title = title
        self.url = url
        self.content = content
        self.source = source  # 来源标识

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "source": self.source,
        }


class MultiSearchClient:
    """多源搜索客户端，按优先级轮换"""

    def __init__(self):
        self.bocha_key = os.getenv("BOCHA_API_KEY", "")
        self.exa_key = os.getenv("EXA_API_KEY", "")
        self.serpapi_key = os.getenv("SERPAPI_KEY", "")
        self.tavily_key = os.getenv("TAVILY_API_KEY", "")

        # 每日使用计数
        self._usage = self._load_usage()
        self._usage_date = date.today().isoformat()

        # 额度限制（保守设置）
        self._limits = {
            "bocha": 30,      # 1000次/3个月 ≈ 11次/天，保守给30
            "exa": 40,        # 1000次/月 ≈ 33次/天，保守给40
            "serpapi": 10,    # 250次/月 ≈ 8次/天，保守给10
            "tavily": 999,    # 付费兜底，不限
        }

    def _load_usage(self) -> dict:
        """从文件加载使用计数"""
        try:
            if _USAGE_FILE.exists():
                data = json.loads(_USAGE_FILE.read_text())
                if data.get("date") == date.today().isoformat():
                    return data.get("counts", {})
        except Exception:
            pass
        return {}

    def _save_usage(self):
        """保存使用计数到文件"""
        try:
            _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _USAGE_FILE.write_text(json.dumps({
                "date": self._usage_date,
                "counts": self._usage,
            }, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.debug(f"保存搜索用量失败: {e}")

    def _reset_if_new_day(self):
        """新的一天重置计数"""
        today = date.today().isoformat()
        if self._usage_date != today:
            self._usage = {}
            self._usage_date = today

    def _record(self, source: str):
        """记录使用"""
        self._usage[source] = self._usage.get(source, 0) + 1
        self._save_usage()

    def _is_available(self, source: str) -> bool:
        """检查源是否可用（有key且未超额度）"""
        key_map = {
            "bocha": self.bocha_key,
            "exa": self.exa_key,
            "serpapi": self.serpapi_key,
            "tavily": self.tavily_key,
        }
        key = key_map.get(source, "")
        if not key or not key.strip():
            return False
        used = self._usage.get(source, 0)
        limit = self._limits.get(source, 0)
        return used < limit

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        执行搜索，按优先级轮换数据源

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            List[Dict]: [{title, url, content, source}]
        """
        self._reset_if_new_day()

        # 按优先级尝试
        sources = ["bocha", "exa", "serpapi", "tavily"]

        for source in sources:
            if not self._is_available(source):
                continue

            try:
                results = self._search_with(source, query, max_results)
                if results and len(results) > 0:
                    self._record(source)
                    logger.info(f"🔍 搜索成功 [{source}] query='{query[:30]}...' 返回{len(results)}条")
                    return results
                else:
                    logger.info(f"⚠️ [{source}] 返回空结果，尝试下一个")
            except Exception as e:
                logger.warning(f"⚠️ 搜索失败 [{source}]: {e}")
                continue

        logger.error(f"❌ 所有搜索源均失败: {query[:50]}")
        return []

    def _search_with(self, source: str, query: str, max_results: int) -> List[Dict]:
        """调用具体的搜索源"""
        if source == "bocha":
            return self._search_bocha(query, max_results)
        elif source == "exa":
            return self._search_exa(query, max_results)
        elif source == "serpapi":
            return self._search_serpapi(query, max_results)
        elif source == "tavily":
            return self._search_tavily(query, max_results)
        return []

    def _search_bocha(self, query: str, max_results: int) -> List[Dict]:
        """BochaAI 搜索"""
        import requests

        url = "https://api.bochaai.com/v1/web-search"
        headers = {
            "Authorization": f"Bearer {self.bocha_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "count": max_results,
            "summary": True,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # BochaAI 格式: {code, data: {webPages: {value: [{name, url, snippet, summary}]}}}
        web_pages = data.get("data", {}).get("webPages", {})
        items = web_pages.get("value", [])

        results = []
        for item in items[:max_results]:
            content = item.get("summary", "") or item.get("snippet", "")
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "content": content[:500],
                "source": "bocha",
            })
        return results

    def _search_exa(self, query: str, max_results: int) -> List[Dict]:
        """Exa.ai 搜索"""
        import requests

        url = "https://api.exa.ai/search"
        headers = {
            "x-api-key": self.exa_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "num_results": max_results,
            "type": "neural",
            "contents": {
                "text": {"max_characters": 500}
            },
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("text", item.get("highlight", ""))[:500],
                "source": "exa",
            })
        return results

    def _search_serpapi(self, query: str, max_results: int) -> List[Dict]:
        """SerpAPI 搜索（Google结果）"""
        import requests

        params = {
            "q": query,
            "api_key": self.serpapi_key,
            "engine": "google",
            "num": max_results,
            "hl": "zh-cn",
            "gl": "cn",
        }

        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("organic_results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "content": item.get("snippet", "")[:500],
                "source": "serpapi",
            })
        return results

    def _search_tavily(self, query: str, max_results: int) -> List[Dict]:
        """Tavily 搜索（兜底）"""
        try:
            from tavily import TavilyClient as _TC
        except ImportError:
            logger.warning("tavily-python 未安装")
            return []

        # 清除 socks 代理（Tavily 需要直连）
        proxy_keys = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")
        saved = {k: os.environ.pop(k) for k in proxy_keys if k in os.environ}
        try:
            client = _TC(api_key=self.tavily_key)
            response = client.search(
                query=query,
                max_results=max_results,
                search_depth="basic",
            )
        finally:
            os.environ.update(saved)

        results = []
        for item in response.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", "")[:500],
                "source": "tavily",
            })
        return results

    def get_usage_summary(self) -> str:
        """获取今日使用量摘要"""
        self._reset_if_new_day()
        parts = []
        for source in ["bocha", "exa", "serpapi", "tavily"]:
            used = self._usage.get(source, 0)
            limit = self._limits.get(source, 0)
            parts.append(f"{source}:{used}/{limit}")
        return " | ".join(parts)


# 单例
_client: Optional[MultiSearchClient] = None


def get_search_client() -> MultiSearchClient:
    """获取搜索客户端单例"""
    global _client
    if _client is None:
        _client = MultiSearchClient()
    return _client
