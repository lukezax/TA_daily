# LLM 输出重试机制（备用方案）

## 背景

TradingAgents 的各 Agent 节点调用 LLM 生成分析报告时，可能出现输出过短或截断的情况：
- `investment_plan.md` 只有几个字（如"咱们来"）
- `research_team_decision.md` 辩论内容在句子中间截断
- 其他报告内容不完整

**主要原因**：`max_tokens` 参数限制了 LLM 输出长度。已通过将 `max_tokens` 从 4000 调整为 131072 解决。

**本文档为备用方案**：如果未来仍出现截断（如模型本身限制、网络中断等），可实施以下重试机制。

---

## 方案设计

### 检测规则

```python
# 各报告的最小有效输出阈值（字符数）
MIN_OUTPUT_THRESHOLDS = {
    "market_report": 500,           # 市场技术分析
    "fundamentals_report": 300,     # 基本面分析
    "news_report": 200,             # 新闻分析
    "sentiment_report": 100,        # 情绪分析
    "investment_plan": 200,         # 投资组合决策（研究经理）
    "trader_investment_plan": 200,  # 交易员计划
    "final_trade_decision": 100,    # 最终投资决策（风控经理）
}
```

### 修改位置

**文件**：`TradingAgents-CN/tradingagents/graph/trading_graph.py`

**位置**：在各 Agent 节点执行完毕、结果写入 state 之后，保存到文件之前。

### 实现代码

```python
# 在 trading_graph.py 中添加

import logging
logger = logging.getLogger(__name__)

MIN_OUTPUT_THRESHOLDS = {
    "market_report": 500,
    "fundamentals_report": 300,
    "news_report": 200,
    "sentiment_report": 100,
    "investment_plan": 200,
    "trader_investment_plan": 200,
    "final_trade_decision": 100,
}


def check_and_retry_output(field_name: str, content: str, retry_func, state: dict, max_retries: int = 1) -> str:
    """
    检测 Agent 输出是否过短，如果是则重试。

    Args:
        field_name: 报告字段名（如 "investment_plan"）
        content: Agent 当前输出内容
        retry_func: 重试时调用的函数（Agent 节点函数）
        state: 当前 graph state
        max_retries: 最大重试次数

    Returns:
        最终输出内容（可能是原始内容或重试后的内容）
    """
    threshold = MIN_OUTPUT_THRESHOLDS.get(field_name, 100)

    # 检测是否过短
    if content and len(content.strip()) >= threshold:
        return content  # 正常，不需要重试

    original_len = len(content.strip()) if content else 0
    logger.warning(
        f"⚠️ [{field_name}] 输出过短 ({original_len}字 < {threshold}字阈值)，"
        f"尝试重试 (最多{max_retries}次)..."
    )

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔄 [{field_name}] 第{attempt}次重试...")
            retry_result = retry_func(state)

            # 从重试结果中提取对应字段
            retry_content = ""
            if isinstance(retry_result, dict):
                retry_content = retry_result.get(field_name, "")
            elif isinstance(retry_result, str):
                retry_content = retry_result

            if retry_content and len(retry_content.strip()) >= threshold:
                logger.info(
                    f"✅ [{field_name}] 重试成功 "
                    f"({len(retry_content.strip())}字 >= {threshold}字阈值)"
                )
                return retry_content
            else:
                logger.warning(
                    f"⚠️ [{field_name}] 第{attempt}次重试仍过短 "
                    f"({len(retry_content.strip()) if retry_content else 0}字)"
                )

        except Exception as e:
            logger.error(f"❌ [{field_name}] 第{attempt}次重试异常: {e}")

    # 所有重试都失败
    logger.error(
        f"❌ [{field_name}] {max_retries}次重试后仍过短，标记为不完整"
    )

    # 在内容末尾追加警告
    warning = "\n\n---\n⚠️ 注意：此内容可能不完整（LLM 输出被截断，重试后仍未恢复）"
    return (content or "") + warning
```

### 集成方式

在 `trading_graph.py` 的报告保存逻辑中调用：

```python
# 示例：在研究经理节点后
investment_plan = state.get("investment_plan", "")
investment_plan = check_and_retry_output(
    field_name="investment_plan",
    content=investment_plan,
    retry_func=research_manager_node,  # 重新调用研究经理
    state=state,
    max_retries=1
)
state["investment_plan"] = investment_plan
```

### 注意事项

1. **执行时间**：每次重试 = 多一次 LLM 调用 ≈ 30-120 秒（取决于模型速度）
2. **成本**：重试会消耗额外的 token（输入 token 不变，输出 token 翻倍）
3. **幂等性**：Agent 节点应该是幂等的（相同输入产生相同输出），重试不会产生副作用
4. **并发安全**：如果多只股票并行分析，重试不会影响其他股票的分析流程

---

## 替代方案：仅检测+标记（不重试）

如果不想增加执行时间，可以只做检测和标记：

```python
def mark_incomplete_output(field_name: str, content: str) -> str:
    """检测输出是否过短，如果是则追加警告标记"""
    threshold = MIN_OUTPUT_THRESHOLDS.get(field_name, 100)

    if content and len(content.strip()) >= threshold:
        return content

    logger.warning(f"⚠️ [{field_name}] 输出过短 ({len(content.strip()) if content else 0}字)")
    warning = "\n\n---\n⚠️ 此内容可能不完整（LLM 输出被截断）"
    return (content or "") + warning
```

---

## 当前状态

- `max_tokens` 已从 4000 调整为 131072（2026-05-14）
- 预期截断问题已解决
- 本文档作为备用方案存档，如果未来再次出现截断可直接实施
