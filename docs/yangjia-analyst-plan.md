# 养家视角分析师 — 实施方案

## 定位

第 6 个独立分析师节点，用"炒股养家"的完整思维框架解读真实市场数据。

- 数据来源：本地 `stock_data/*.json`（Python 代码提取，确定性数字）
- 思维框架：`chaoguyangjia-perspective/SKILL.md` **完整注入** system prompt
- 输出：养家风格的情绪研判 + 赢面评估 + 仓位建议

## 数据流

```
stock_data/{code}_d.json  ─┐
                            ├─→ Python 提取指标（代码计算，无幻觉）
stock_data/{code}_realtime_d.json ─┘
                                        ↓
                              结构化数据 JSON
                                        ↓
        ┌─────────────────────────────────────────┐
        │  LLM                                     │
        │  System: SKILL.md 完整内容               │
        │  User: "以下是{code}的真实数据: {...}"    │
        │         "请用你的框架分析"               │
        └─────────────────────────────────────────┘
                                        ↓
                              yangjia_report (Markdown)
```

## Python 提取的指标（传给 LLM 的真实数据）

```python
def _extract_yangjia_signals(kline_data: list, realtime_data: dict) -> dict:
    """
    从真实K线+实时行情提取养家框架关注的指标
    所有数字由Python计算，不让LLM推算
    """
    return {
        # === 价格位置 ===
        "当前价格": close,
        "5日涨幅%": pct_5d,
        "10日涨幅%": pct_10d,
        "20日涨幅%": pct_20d,
        "价格在60日区间位置%": position_in_60d,  # 0=60日最低点，100=60日最高点
        "距60日高点%": dist_to_60d_high,
        "距60日低点%": dist_to_60d_low,

        # === 量能（赚钱效应的资金指标）===
        "当日成交量/5日均量": vol_ratio_5d,
        "当日成交量/20日均量": vol_ratio_20d,
        "换手率%": hs,
        "量比": lb,

        # === 波动特征 ===
        "当日振幅%": amplitude,
        "5日平均振幅%": avg_amplitude_5d,
        "连续上涨天数": consecutive_up_days,   # 负值表示连续下跌
        "当日涨幅%": today_pct,

        # === 养家式赢面计算 ===
        "上方空间%(至60日高点)": upside,
        "下方风险%(至60日低点)": downside,
        "风险收益比": risk_reward_ratio,  # upside / downside

        # === 情绪参考（来自realtime）===
        "60日涨幅%": zdf60,
        "年初至今涨幅%": zdfnc,

        # === 数据可用性 ===
        "K线天数": len(kline_data),
        "数据截止日": last_date,
    }
```

## LLM Prompt 结构

```
[System Prompt]
────────────────────────────────────
{SKILL.md 完整内容，约8000字}
────────────────────────────────────

[User Prompt]
────────────────────────────────────
以下是股票 {ticker}（{stock_name}）的真实市场数据（由系统计算，非推测）：

{signals 的 JSON 格式化展示}

请基于以上真实数据，用你的交易框架给出分析：
1. 情绪阶段判断（基于量能变化和涨跌趋势）
2. 赢面评估（基于风险收益比，给出具体百分比）
3. 仓位建议（参照你的赢面仓位表）
4. 空仓测试（如果现在空仓，你会买入吗？为什么？）
5. 关键风险提示

注意：
- 所有数字已由系统计算，请直接引用，不要重新估算
- 你只能看到个股数据，无法看到全市场涨停家数等，
  如需这些信息请标注"需要补充全市场数据"
- 使用人民币(¥)作为价格单位
────────────────────────────────────
```

## 节点设计

```python
# yangjia_analyst.py

def create_yangjia_analyst(llm, config: dict = None):
    """创建养家视角分析师节点"""
    config = config or {}
    stock_data_dir = config.get("stock_data_dir", "stock_data")

    # 启动时加载 SKILL.md 完整内容
    skill_path = Path(__file__).resolve().parents[4] / "chaoguyangjia-perspective" / "SKILL.md"
    # 也支持环境变量覆盖路径
    skill_path_override = os.getenv("YANGJIA_SKILL_PATH")
    if skill_path_override:
        skill_path = Path(skill_path_override)

    if skill_path.exists():
        SKILL_CONTENT = skill_path.read_text(encoding="utf-8")
    else:
        SKILL_CONTENT = "（养家SKILL文件未找到，降级为通用短线分析师）"
        logger.warning(f"⚠️ [养家分析师] SKILL.md 未找到: {skill_path}")

    def yangjia_analyst_node(state) -> dict:
        ticker = state["company_of_interest"]
        trade_date = state.get("trade_date", "")

        # 1. 加载本地真实数据
        kline_data = _load_kline_data(ticker, stock_data_dir)
        realtime_data = _load_realtime_data(ticker, stock_data_dir)

        if kline_data is None or len(kline_data) < 60:
            return {
                "yangjia_report": f"养家视角分析：{ticker} 本地K线数据不足，跳过。"
            }

        # 2. Python 计算指标（确定性，无幻觉）
        signals = _extract_yangjia_signals(kline_data, realtime_data)

        # 3. LLM 用养家框架解读数据
        signals_text = json.dumps(signals, ensure_ascii=False, indent=2)

        user_prompt = f"""以下是股票 {ticker} 的真实市场数据（由系统计算，非推测）：

{signals_text}

请基于以上真实数据，用你的交易框架给出分析：
1. 情绪阶段判断（基于量能变化和涨跌趋势推断个股情绪状态）
2. 赢面评估（基于风险收益比，给出具体百分比）
3. 仓位建议（参照你的赢面仓位表）
4. 空仓测试（如果现在空仓，你会买入吗？为什么？）
5. 关键风险提示

注意：所有数字已由系统计算，请直接引用不要重新估算。使用人民币(¥)。"""

        response = llm.invoke([
            {"role": "system", "content": SKILL_CONTENT},
            {"role": "user", "content": user_prompt},
        ])

        return {"yangjia_report": response.content}

    return yangjia_analyst_node
```

## 注册到 LangGraph

| 文件 | 改动 |
|------|------|
| `agents/analysts/yangjia_analyst.py` | **新建**，核心逻辑 |
| `agents/analysts/__init__.py` | 加 `from .yangjia_analyst import create_yangjia_analyst` |
| `graph/setup.py` | 注册 `"yangjia"` 节点（跟 czsc 一样，无 tools） |
| `graph/propagation.py` | state 加 `"yangjia_report": ""` |
| `graph/trading_graph.py` | 名称映射加 `'Yangjia Analyst': "🎯 养家视角"` |
| `pipeline/config.py` | `selected_analysts` 默认值加 `"yangjia"` |
| `pipeline_config.yaml` | 加 `- yangjia` |

## 与 czsc 的对比

| 维度 | czsc | yangjia |
|------|------|---------|
| 计算引擎 | czsc 包（Rust 实现） | 纯 Python（简单数学） |
| LLM 作用 | 翻译结构化信号为可读报告 | 用完整思维框架解读数据给出决策 |
| System Prompt | 简短的格式要求 | SKILL.md 完整内容（~8000字） |
| 数据来源 | stock_data/{code}_d.json | stock_data/{code}_d.json + _realtime_d.json |
| Tools | 不需要 | 不需要 |
| 执行顺序 | 可并行 | 可并行（不依赖其他分析师） |
| 输出 | czsc_report + czsc_signals | yangjia_report |

## Token 消耗预估

- System prompt（SKILL.md）：约 8000 字 ≈ ~5000 tokens
- User prompt（指标数据）：约 500 字 ≈ ~300 tokens
- 输出：约 800-1500 字 ≈ ~800 tokens
- 每只股票总消耗：**~6100 tokens**
- 用本地 LLM（llama.cpp）：无费用
- 用云端模型：每只约 ¥0.01-0.03

## 降级策略

- SKILL.md 文件不存在 → 降级为通用短线分析师（简短 prompt）
- K线数据不足 → 返回"数据不足，跳过"
- LLM 调用失败 → 返回简短模板化报告（类似 czsc 的 fallback）
