# TradingAgents 抗幻觉优化方案

**日期**: 2026-06-15  
**问题**: LLM 在数据获取失败时编造技术指标，导致分析报告包含严重幻觉

---

## 一、问题根因

000519 案例的完整链路：

```
Pipeline 21:00 筛选通过 000519 → 提交给 TradingAgents 分析（凌晨02:38）
→ Tushare 获取数据失败（无日线数据）
→ AKShare 获取失败（东方财富被封）
→ Zhitu 未被调用（当时还没加 fallback）
→ MongoDB 缓存中可能有旧数据（但不完整）
→ LLM 拿到残缺/零数据，但没有报告"数据缺失"
→ LLM 自行编造了完整的 MACD/KDJ/MA/成交量数据
→ 生成了看似逻辑自洽但完全错误的分析报告
→ 最终决策"买入 目标价18.74"（但实际价19.10，目标价比现价还低）
```

**核心问题**：系统没有任何环节验证"LLM 声称的数据"是否与"实际获取的数据"一致。

---

## 二、优化方案（3层防御）

### 第1层：数据获取层 — 确保拿到数据再分析

**改动位置**: `tradingagents/utils/stock_validator.py` → `_prepare_china_stock_data_async`

**方案**：

在股票代码验证阶段（分析开始前），加强数据完整性检查：

```python
# 当前逻辑（简化）：
if not validation_result.is_valid:
    # 标记失败，不分析
    return

# 优化后：
if not validation_result.has_historical_data:
    # 有基本信息但没有历史数据 → 不让 LLM 分析，直接标记为"数据不足"
    error_msg = f"数据不足：无法获取 {stock_code} 的历史K线数据，跳过分析"
    await update_task_status(task_id, FAILED, error_message=error_msg)
    return
```

**关键变化**：
- 当前：只要 `is_valid=True`（能找到股票代码），就继续分析
- 优化后：`is_valid=True` 且 `has_historical_data=True` 且 **历史数据条数 ≥ 60** 才继续

**预期效果**：数据源全挂时，分析任务直接标记失败，不会产生幻觉报告。

---

### 第2层：Prompt 层 — 强制传入结构化数据，禁止 LLM 编造

**改动位置**: `tradingagents/agents/` 下各 analyst 节点的 prompt

**方案 A：在 market analyst 的 prompt 前注入结构化数据块**

当前的流程是：data_flow 获取数据 → 格式化为文本 → 传给 LLM。问题在于格式化后的文本可能不包含完整指标，LLM 就自己补。

优化：在传入 LLM 的 context 中显式包含一个 **"原始数据清单"**，并在 system prompt 中加入硬约束：

```markdown
## 原始数据（以下为系统提供的真实数据，你必须且只能使用这些数据）

### K线数据（最近5天）
| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 |
|------|------|------|------|------|--------|
| 2026-06-11 | 18.68 | 18.99 | 18.22 | 18.74 | 467053 |
| ... |

### 技术指标（系统计算）
- MACD: DIF=0.055, DEA=0.023, 柱=0.064
- KDJ: K=38.36, D=36.68, J=41.72
- MA5=18.81, MA10=?, MA20=?, MA60=?
- BOLL: 上轨=9.76, 中轨=9.53, 下轨=9.31

### 数据可用性声明
- 历史K线: ✅ 可用（来源: zhitu, 239条）
- MACD: ✅ 可用（来源: zhitu）
- 实时行情: ❌ 不可用（所有源失败）
- 财务数据: ❌ 不可用

## 铁律
1. 你只能引用上面"原始数据"中的数值
2. 如果某个指标标记为"❌ 不可用"，你必须说"该数据暂不可用"，不得编造
3. 你的报告中出现的每个数字都必须能在上面的数据表中找到来源
```

**方案 B：指标由代码计算，不让 LLM 计算**

当前：LLM 自己从 K线数据推导 MACD/KDJ/RSI 等（容易算错或编造）

优化：**所有技术指标由 Python 代码预先计算好**，直接以结构化数据传入 LLM。LLM 只负责"解读"，不负责"计算"。

```python
# 在 data_flow 层：
def prepare_market_data_for_llm(stock_code, date):
    kline = get_kline(stock_code, limit=60)  # 历史K线
    
    # Python 计算指标（确定性计算，不依赖 LLM）
    indicators = {
        "macd": calculate_macd(kline),
        "kdj": calculate_kdj(kline),
        "rsi": calculate_rsi(kline),
        "ma": calculate_ma(kline, [5, 10, 20, 60]),
        "boll": calculate_boll(kline),
    }
    
    # 格式化为 LLM 可读的结构化文本
    return format_structured_data(kline, indicators)
```

**推荐方案 B**。原因：
- LLM 不擅长精确数学计算
- 指标计算是确定性逻辑，应该由代码完成
- 减少 LLM 的"创造空间"，降低幻觉概率

---

### 第3层：输出校验层 — 分析结果 post-check

**改动位置**: `app/services/simple_analysis_service.py` → `execute_analysis_background` 的报告保存阶段

**方案**：在保存最终决策前，对关键数值做 sanity check：

```python
def validate_final_decision(decision: dict, actual_data: dict) -> dict:
    """校验最终决策是否合理"""
    issues = []
    
    # 1. 目标价 vs 当前价
    current_price = actual_data.get("close", 0)
    target_price = decision.get("target_price", 0)
    action = decision.get("action", "")
    
    if "买" in action and target_price > 0 and target_price < current_price:
        issues.append(f"买入建议但目标价({target_price})低于当前价({current_price})")
    
    if "卖" in action and target_price > 0 and target_price > current_price * 1.5:
        issues.append(f"卖出建议但目标价({target_price})远高于当前价({current_price})")
    
    # 2. 置信度合理性
    confidence = decision.get("confidence", 0)
    if confidence > 95:
        issues.append(f"置信度异常高({confidence}%)，可能是幻觉")
    
    # 3. 报告中的价格 vs 实际最新价
    # 从报告文本中提取"当前价格"并与实际比对
    reported_price = extract_price_from_report(decision.get("summary", ""))
    if reported_price and abs(reported_price - current_price) / current_price > 0.03:
        issues.append(f"报告中的价格({reported_price})与实际价格({current_price})偏差>3%")
    
    if issues:
        decision["validation_warnings"] = issues
        decision["validated"] = False
    else:
        decision["validated"] = True
    
    return decision
```

**展示层处理**：

在报告模板中，如果 `validated=False`：
```html
{% if not stock.analysis.validated %}
<div class="validation-warning">
  ⚠️ 数据校验警告：{{ stock.analysis.validation_warnings | join('; ') }}
</div>
{% endif %}
```

---

## 三、实施优先级

| 优先级 | 方案 | 改动量 | 效果 | 风险 |
|--------|------|--------|------|------|
| **P0** | 第1层：数据不足时阻断分析 | 小（~20行） | 杜绝"无数据瞎分析" | 低（只是提前失败） |
| **P1** | 第2层B：指标由代码计算 | 中（~100行） | 消除 LLM 计算错误和编造指标 | 中（需要验证计算逻辑） |
| **P2** | 第3层：输出 post-check | 小（~50行） | 给用户明确的"可信度"标记 | 低 |
| **P3** | 第2层A：prompt 强制约束 | 小（改 prompt） | 辅助效果，减少但不能杜绝幻觉 | 低 |

---

## 四、与现有改动的关系

| 已完成的改动 | 对幻觉问题的影响 |
|-------------|----------------|
| 数据源优先级调整 + zhitu fallback | ✅ 减少"数据获取全挂"的概率（以前只有东方财富一条路） |
| 多源搜索替换 Tavily | 不直接影响（搜索是情绪数据，不是K线指标） |
| 策略研究员 proxy 修复 | 不直接影响 |

**关键点**：数据源 fallback 解决的是"拿不到数据"的概率问题，但即使 fallback 到了 zhitu 拿到了数据，LLM 仍可能在**解读和引用数据时**产生幻觉（把0.036写成0.36、把DIF和DEA搞反等）。所以第2层和第3层仍然必要。

---

## 五、预期效果

优化前（当前）：
```
数据获取失败 → LLM 编造数据 → 输出看起来正确的报告 → 用户被误导
```

优化后（P0+P1+P2）：
```
数据获取失败 → 第1层拦截，任务标记"数据不足"，不输出报告
数据获取成功 → 指标由代码计算（第2层） → LLM 只解读不计算
                → 输出决策 → 第3层校验（目标价/置信度/价格一致性）
                → 通过 → 正常展示
                → 不通过 → 展示但带 ⚠️ 警告标记
```
