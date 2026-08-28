# SignalProcessor 目标价提取修正方案

## 问题描述

`SignalProcessor.process_signal()` 在从 `final_trade_decision` 文本中提取 `target_price` 时，偶发提取到错误的价格数字。

**案例：603110 东方材料（2026-05-29）**
- 当前价：¥23.41
- trader_investment_plan 给出的目标价：¥10-22（分时间段）
- SignalProcessor 提取的 target_price：¥5.18（来自基本面报告中的 PE 理论估值）
- 偏离度：-78%，明显错误

## 根因分析

1. `final_trade_decision` 文本中包含多个价格数字（当前价、各种估值、各时间段目标价）
2. `SignalProcessor` 用一个独立的 LLM 调用从文本中提取 JSON，这个 LLM 没有参与前面的推理过程
3. LLM 在十几个数字中选错了——把基本面报告中的理论估值当成了目标价

## 设计原则

- 尊重多 agent 辩论的推理结果，不用硬规则覆盖
- 只在明显出错时做修正，不改变正常情况的行为
- 修正时给 LLM 明确的上下文和错误点，让它做有针对性的判断

## 修正方案

### 流程

```
现有逻辑提取 target_price
        │
        ▼
校验：|target_price - 当前价| / 当前价 > 60% ?
        │
        ├── 否 → 正常，直接使用
        │
        └── 是 → 触发修正
                │
                ▼
        构造修正 prompt：
        - 当前股价
        - trader_investment_plan 全文
        - 错误的 target_price 及偏离度
        - 要求给出合理的目标价
                │
                ▼
        LLM 返回修正后的 target_price
                │
                ▼
        二次校验：修正后的价格是否合理？
        - 合理 → 使用修正值
        - 仍不合理 → 设为 None，日志告警
```

### 校验阈值

- **±60%** 作为触发修正的阈值
- 理由：B1/B2 筛选出的股票短期目标价通常在 ±30% 以内；即使是"卖出"建议的止损目标，也不会偏离当前价 60% 以上
- 如果 LLM 给出的目标价偏离 60% 以上，几乎可以确定是提取错误

### 修正 Prompt

```
当前股价是 {currency_symbol}{current_price}。

以下是经过多 agent 辩论后，交易员给出的投资计划：
---
{trader_investment_plan 文本}
---

之前系统提取的目标价是 {currency_symbol}{wrong_price}，
偏离当前价 {deviation}%，明显不合理。

请根据上述投资计划中的分析结论，给出一个合理的目标价（仅返回数字）。
如果投资计划建议卖出，给出短期（1个月内）的目标卖出价。
如果建议买入，给出短期目标价。
如果建议持有，给出合理价格区间的中值。
```

### 需要的输入

- `current_price`：当前股价（从 state 中的实时行情数据获取）
- `trader_investment_plan`：交易员投资计划文本（从 state 中获取）
- `wrong_price`：第一次提取的错误目标价
- `deviation`：偏离百分比

### 改动范围

仅修改一个文件：
```
TradingAgents-CN/tradingagents/graph/signal_processing.py
```

在 `process_signal()` 方法中，现有提取逻辑之后、返回 result 之前，插入校验+修正步骤。

### 需要传入的额外参数

`process_signal(full_signal, stock_symbol=None)` 需要增加参数：
- `current_price: float = None` — 当前股价
- `trader_plan: str = None` — trader_investment_plan 文本

调用方（`trading_graph.py` 第 868 行）需要同步修改，从 `final_state` 中传入这两个值。

## 预期效果

- 正常情况（95%+）：校验通过，不触发修正，零额外开销
- 异常情况（<5%）：触发一次轻量 LLM 调用（prompt 很短，只需返回一个数字），修正目标价
- 极端情况：修正后仍不合理，设为 None，不瞎猜

## 风险

- 额外 LLM 调用增加约 2-3 秒延迟（仅异常时触发）
- 阈值 60% 可能需要根据实际运行数据调整
- 如果 `current_price` 获取不到（state 中没有），则跳过校验（不影响现有逻辑）

## 状态

待实施。
