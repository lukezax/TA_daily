# 修复 httpx socks 代理协议错误

## 问题描述

当系统配置了 SOCKS 代理（如 Clash、V2Ray 等），Python 程序通过 `httpx`（OpenAI SDK 底层 HTTP 客户端）连接**本地服务**时报错：

```
ValueError: Unknown scheme for proxy URL URL('socks://127.0.0.1:6244/')
```

或：

```
ValueError: Unknown scheme for proxy URL URL('socks5://127.0.0.1:7890/')
```

## 根因

1. 系统或 shell 中设置了 `ALL_PROXY=socks://127.0.0.1:6244` 等环境变量
2. `httpx >= 0.28` 在创建 `Client` 实例时自动读取 `ALL_PROXY`/`HTTP_PROXY`/`HTTPS_PROXY` 环境变量
3. `httpx` 不原生支持 `socks://` 协议（需要额外安装 `httpx[socks]`），遇到 socks 协议直接报错
4. 即使传入 `proxy=None`，httpx 仍然会读取环境变量中的代理配置

## 解决方案

### 方案 1：安装 httpx socks 支持（最简单）

如果你确实需要通过 socks 代理访问外部 API：

```bash
pip install httpx[socks]
```

这会安装 `socksio` 包，让 httpx 支持 socks5 协议。

### 方案 2：代码中临时清除代理环境变量（推荐用于本地服务）

当你的程序需要连接**本地服务**（如本地 LLM、本地 API）时，代理是多余的。在创建 httpx/OpenAI 客户端前临时清除代理变量：

```python
import os
import threading
from urllib.parse import urlparse

# 线程锁保证并发安全
_proxy_env_lock = threading.Lock()

_PROXY_ENV_KEYS = (
    "ALL_PROXY", "all_proxy",
    "HTTP_PROXY", "http_proxy",
    "HTTPS_PROXY", "https_proxy",
)


def _is_local_url(url: str) -> bool:
    """判断 URL 是否指向本地地址"""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    except Exception:
        return False


def _clear_proxy_env() -> dict:
    """临时清除代理环境变量，返回被清除的变量用于恢复"""
    saved = {}
    for key in _PROXY_ENV_KEYS:
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    return saved


def _restore_proxy_env(saved: dict):
    """恢复之前清除的代理环境变量"""
    os.environ.update(saved)


# 使用示例
def create_client(base_url: str):
    if _is_local_url(base_url):
        with _proxy_env_lock:
            saved = _clear_proxy_env()
            try:
                # 在这里创建 httpx/OpenAI 客户端
                from openai import OpenAI
                client = OpenAI(base_url=base_url, api_key="any")
            finally:
                _restore_proxy_env(saved)
        return client
    else:
        from openai import OpenAI
        return OpenAI(base_url=base_url)
```

### 方案 3：配置 NO_PROXY 环境变量

在 `.env` 或 shell 中配置 `NO_PROXY`，让本地地址和国内域名绕过代理：

```bash
# .env 或 ~/.bashrc
NO_PROXY=localhost,127.0.0.1,0.0.0.0,::1,eastmoney.com,push2.eastmoney.com,api.tushare.pro,baostock.com
```

⚠️ 注意：`NO_PROXY` 对 httpx 的 socks 代理**不一定生效**（取决于 httpx 版本），方案 2 更可靠。

### 方案 4：将 socks 代理转为 http 代理

大多数代理工具（Clash、V2Ray）同时提供 HTTP 代理端口。改用 HTTP 协议：

```bash
# 不要用 socks://
# ALL_PROXY=socks://127.0.0.1:6244  ❌

# 改用 http://
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
```

httpx 原生支持 `http://` 代理，不需要额外安装包。

## 常见代理工具的 HTTP 端口

| 工具 | SOCKS 端口 | HTTP 端口（推荐使用） |
|------|-----------|---------------------|
| Clash | socks5://127.0.0.1:7891 | http://127.0.0.1:7890 |
| V2Ray | socks5://127.0.0.1:10808 | http://127.0.0.1:10809 |
| Shadowsocks | socks5://127.0.0.1:1080 | http://127.0.0.1:1081 |
| Clash Verge | socks5://127.0.0.1:7891 | http://127.0.0.1:7890 |

## 排查步骤

```bash
# 1. 检查当前代理环境变量
env | grep -i proxy

# 2. 如果看到 socks:// 开头的值，改为 http:// 或清除
unset ALL_PROXY all_proxy

# 3. 测试连接
python -c "from openai import OpenAI; c = OpenAI(base_url='http://127.0.0.1:8080/v1', api_key='test'); print('OK')"
```

## 适用场景

| 场景 | 推荐方案 |
|------|---------|
| 本地 LLM（Ollama/vLLM/LMStudio） | 方案 2（代码清除代理） |
| 需要代理访问 OpenAI/Claude API | 方案 4（改用 http 代理）或方案 1（安装 socks 支持） |
| 国内数据源（东方财富/Tushare） | 方案 3（NO_PROXY 配置） |
| 混合场景（本地 LLM + 外部 API） | 方案 2 + 方案 4 组合 |
