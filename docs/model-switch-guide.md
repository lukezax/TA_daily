# 模型切换指南

> 服务器（token-plan API Base）和 API Key 固定不变，只需修改模型名称即可切换。
> 以下说明涵盖所有需要修改的位置。

---

## 架构概览

```
Pipeline (--deep) ──HTTP──▶ TradingAgents-CN API ──▶ graph/LLM Client
   │                             │
   │ 发送:                       │ 从 settings.json / 内存覆写
   │ deep_analysis_model         │ 读取 deep_analysis_model
   │ = "qwen3.7-max"             │ → 交给 graph，graph 根据 provider
   │                             │   选择对应 LLM 客户端
```

**核心原则：**
- `deep_analysis_model` 的值只是一个模型**名称**（字符串标识）
- 真正的 API 路由（用哪个 endpoint、哪个 key）由 `provider` 决定
- 只要 provider 解析为 `qwen`，就会走 token-plan 服务器（已在 MongoDB `llm_providers` 中配置）

---

## 切换模型需要修改的文件

### 1️⃣ Pipeline 侧（发起 HTTP 请求方）

**文件：`pipeline/analysis_client.py`**

```python
# 第 197 行
"deep_analysis_model": "qwen3.7-max" if deep_mode else "local",
```

将 `"qwen3.7-max"` 替换为你想要的新模型名：

```python
"deep_analysis_model": "glm-5.2" if deep_mode else "local",
```

---

### 2️⃣ TradingAgents-CN 侧（服务端默认值）

**文件：`TradingAgents-CN/app/__main__.py`**

```python
# 第 127 行（--deep 启动时的内存覆写）
settings_cache["deep_analysis_model"] = "qwen3.7-max"
```

将 `"qwen3.7-max"` 替换为相同的新模型名：

```python
settings_cache["deep_analysis_model"] = "glm-5.2"
```

> 这里修改的是 `unified_config` 内存缓存，不影响 `settings.json` 文件。
> 仅在使用 `python -m app --deep` 时才生效。

---

### 3️⃣ Token-Plan 可用模型列表（可选，但推荐补全）

**文件：`key`**

`key` 文件列出了 token-plan 支持的所有模型。如果新模型已经存在，可跳过此步。

```json
"models": {
    "qwen3.7-max": {
        "name": "Qwen3.7 Max",
        "options": {
            "thinking": { "type": "enabled", "budgetTokens": 8192 }
        }
    },
    "glm-5.2": {           // ← 如果需要新增
        "name": "GLM-5.2",
        "options": {
            "thinking": { "type": "enabled", "budgetTokens": 8192 }
        }
    },
    ...
}
```

> 此文件是 OpenCode / AI 客户端的配置，不直接影响 TradingAgents-CN 的运行。
> 但保持它同步有利于未来兼容。

---

### 4️⃣ TradingAgents-CN 本地模型注册（如果模型不在 `models.json` 中）

**文件：`TradingAgents-CN/config/models.json`**

```json
{
    "provider": "dashscope",
    "model_name": "qwen3.7-max",     // ← 模型名
    "api_key": "",
    "base_url": null,                 // null = 使用 provider 默认 URL
    "max_tokens": 8192,
    "temperature": 0.7,
    "enabled": true
}
```

添加新条目后，TradingAgents-CN 的 `analysis_service.py` 就能通过模型名称找到对应的 provider 配置。

> **注意**：`models.json` 中的 `api_key` 是空字符串。实际的 API Key 储存在 MongoDB `llm_providers` 集合中。
> token-plan 的 provider 已在 MongoDB 中配置好，因此 `api_key: ""` 也能正常工作。

---

### 5️⃣ Provider 回退映射（仅在数据库查询失败时使用）

**文件：`TradingAgents-CN/app/services/simple_analysis_service.py`**

```python
def _get_default_provider_by_model(model_name: str) -> str:
    model_provider_map = {
        'qwen-turbo': 'qwen',
        'qwen-plus': 'qwen',
        'qwen-max': 'qwen',
        ...
    }
    provider = model_provider_map.get(model_name, 'qwen')  # 默认 qwen
```

如果新模型名不在这个字典里，会自动走 `'qwen'` 这个默认值（这正是我们想要的——走 token-plan）。

**除非新模型不是走 token-plan（例如换成 OpenAI），否则不需要修改此文件。**

---

## 检查清单

切换模型后，验证以下内容：

| # | 检查项 | 命令/位置 |
|---|--------|----------|
| 1 | `pipeline/analysis_client.py` 中的模型名已修改 | 第 197 行 |
| 2 | `TradingAgents-CN/app/__main__.py` 中的模型名已同步修改 | 第 127 行 |
| 3 | 新模型在 `key` 文件中存在（推荐） | `key` 文件 `models` 段 |
| 4 | 新模型在 `models.json` 中有条目（推荐） | `config/models.json` |
| 5 | Python 语法检查通过 | `python3 -m py_compile <file>` |
| 6 | 测试 `python -m app --deep` 启动无报错 | 看日志中的 `🔷 深度模式已启用` |

---

## 常见场景

### 场景 A：同一服务商换模型（如 qwen3.7-max → glm-5.2）

只需修改 2 个文件：
1. `pipeline/analysis_client.py` 中的模型名
2. `TradingAgents-CN/app/__main__.py` 中的模型名

### 场景 B：新增一个 token-plan 尚未支持的模型

1. 先确认 token-plan 侧是否支持（看 `key` 文件中是否已有该模型）
2. 如果支持 → 同场景 A
3. 如果不支持 → 需要先在 token-plan 控制台开通，再到 `key` 文件中添加条目

### 场景 C：完全切换服务商（如 token-plan → 直接调用阿里 DashScope）

需要修改：
1. 以上 2 个文件中的模型名
2. `models.json` 中添加新模型（provider 设为 `dashscope`，base_url 填 DashScope endpoint）
3. MongoDB `llm_providers` 中配置新的 API Key
4. `settings.json` 中更新 `deep_backend_url`

---

## 原理说明

### `deep_analysis_model` 的解析链路

```
analysis_service.py
  │
  ├─ task.parameters.deep_analysis_model  (API 请求体指定)
  │     └─ pipeline 发送的 HTTP payload
  │
  └─ unified_config.get_deep_analysis_model()  (服务端默认值)
        └─ settings.json → deep_analysis_model
              OR
        └─ __main__.py 内存覆写（--deep 模式）
              → "qwen3.7-max"

得到 deep_model 字符串后：
  ├─ MongoDB system_configs.llm_configs → 查找 api_base / provider
  │     └─ 未找到则 fallback
  └─ _get_default_provider_by_model() → 返回 provider 名
        └─ "qwen3.7-max" 不在映射表中 → 默认返回 "qwen"

最终 trading_graph.py 根据 provider="qwen" 选择 LLM 客户端，
使用 MongoDB 中配置的 token-plan base_url + api_key。
```

### 为什么模型名可以是任意字符串

模型名本质是一个**Key**，用于在数据库/配置中查找完整的连接信息（api_base、api_key、provider）。只要：

1. 数据库 `system_configs.llm_configs` 中有该模型名的条目（包含 provider、api_base）
2. 或 `_get_default_provider_by_model()` 能返回正确的 provider
3. 且该 provider 在 MongoDB `llm_providers` 中有正确的 base_url 和 api_key

模型名本身可以是任何字符串。
