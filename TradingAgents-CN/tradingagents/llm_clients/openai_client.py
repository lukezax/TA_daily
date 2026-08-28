import logging
import os
import threading
from typing import Any, Optional
from urllib.parse import urlparse

from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

logger = logging.getLogger(__name__)

# 用于保护环境变量临时修改的线程锁
_proxy_env_lock = threading.Lock()

_PROXY_ENV_KEYS = (
    "ALL_PROXY", "all_proxy",
    "HTTP_PROXY", "http_proxy",
    "HTTPS_PROXY", "https_proxy",
)


def _is_local_url(url: Optional[str]) -> bool:
    """判断 URL 是否指向本地地址"""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    except Exception:
        return False


def _clear_proxy_env() -> dict:
    """临时清除代理环境变量，返回被清除的变量用于恢复。

    必须在 _proxy_env_lock 保护下调用。
    """
    saved = {}
    for key in _PROXY_ENV_KEYS:
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    return saved


def _restore_proxy_env(saved: dict):
    """恢复之前清除的代理环境变量。

    必须在 _proxy_env_lock 保护下调用。
    """
    os.environ.update(saved)


class NormalizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI wrapper that normalizes typed content blocks to text."""

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


_PASSTHROUGH_KWARGS = (
    "temperature",
    "max_tokens",
    "timeout",
    "max_retries",
    "callbacks",
    "http_client",
    "http_async_client",
)

_PROVIDER_CONFIG = {
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "glm": ("https://open.bigmodel.cn/api/paas/v4/", "ZHIPU_API_KEY"),
    "qianfan": ("https://qianfan.baidubce.com/v2", "QIANFAN_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "aihubmix": ("https://aihubmix.com/v1", "AIHUBMIX_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
    "custom_openai": (None, "CUSTOM_OPENAI_API_KEY"),
}


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI and OpenAI-compatible providers."""

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        if self.provider in _PROVIDER_CONFIG:
            default_base_url, api_key_env = _PROVIDER_CONFIG[self.provider]
            llm_kwargs["base_url"] = self.base_url or default_base_url
            if api_key_env:
                api_key = self.kwargs.get("api_key") or os.environ.get(api_key_env)
                if api_key:
                    llm_kwargs["api_key"] = api_key
            else:
                llm_kwargs["api_key"] = "ollama"
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url
            api_key = self.kwargs.get("api_key") or os.environ.get("OPENAI_API_KEY")
            if api_key:
                llm_kwargs["api_key"] = api_key

        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        resolved_url = llm_kwargs.get("base_url")
        need_bypass_proxy = resolved_url and _is_local_url(resolved_url)

        if need_bypass_proxy:
            logger.info(
                f"🔧 [代理绕过] 检测到本地地址 {resolved_url}，"
                f"临时清除代理环境变量以避免 httpx socks 协议错误"
            )

        # httpx 0.28+ 在 Client.__init__ 时读取 ALL_PROXY 等环境变量，
        # 且 proxy=None 不能禁用此行为。唯一可靠的方式是在创建实例前
        # 临时清除这些环境变量。使用线程锁保证并发安全。
        if need_bypass_proxy:
            with _proxy_env_lock:
                saved_env = _clear_proxy_env()
                try:
                    logger.info(
                        f"🔧 [代理绕过] 已临时清除 {len(saved_env)} 个代理变量: "
                        f"{list(saved_env.keys())}"
                    )
                    llm = NormalizedChatOpenAI(**llm_kwargs)
                except Exception as e:
                    logger.error(
                        f"❌ [LLM创建失败] model={self.model}, base_url={resolved_url}, "
                        f"provider={self.provider}, error={e}",
                        exc_info=True,
                    )
                    raise
                finally:
                    _restore_proxy_env(saved_env)
                    logger.debug(f"🔧 [代理绕过] 已恢复代理环境变量")
        else:
            try:
                llm = NormalizedChatOpenAI(**llm_kwargs)
            except Exception as e:
                logger.error(
                    f"❌ [LLM创建失败] model={self.model}, base_url={resolved_url}, "
                    f"provider={self.provider}, error={e}",
                    exc_info=True,
                )
                raise

        logger.info(
            f"✅ [LLM创建成功] provider={self.provider}, model={self.model}, "
            f"base_url={resolved_url}, bypass_proxy={need_bypass_proxy}"
        )
        return llm

    def validate_model(self) -> bool:
        return validate_model(self.provider, self.model)
