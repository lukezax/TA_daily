# CICCWM Skills 集成方案

> 日期: 2026-06-29
> 状态: 待确认

## 1. 已安装的 Skills

三个 CICCWM skill 已安装到 `TradingAgents-CN/tradingagents/data_sources/ciccwm/`：

| Skill | 路径 | 功能 |
|-------|------|------|
| market | `ciccwm/market/market_query.py` | 实时行情、K线、资金流向、涨跌排行、关联板块 |
| finance | `ciccwm/finance/finance_query.py` | 财务指标、利润表、现金流、资产负债表 |
| news | `ciccwm/news/get_data.py` | 今日热榜、专题资讯 |

API Key 已配置到 `~/.config/ciccwm/config.json`。

## 2. API 限制测试结果

### 实测结果（2026-06-29）

| 测试项 | 结果 |
|--------|------|
| 连续 10 次 market info | 全部成功，平均 0.5s/次 |
| 8 种接口各调一次 | 全部成功，0.3-0.5s/次 |
| HTTP 响应头 | 无 `X-RateLimit-*` 等限流 header |
| 接口返回体 | 无 quota/limit 相关字段 |
| 脚本代码 | 无 sleep/retry/throttle 逻辑 |

### 结论

**CICCWM API 未观察到明显的调用频率限制。** 连续 10 次请求全部成功，响应头无 rate limit 信息。但需注意：

- 官方文档（SKILL.md）未声明任何 QPS/RPM/日限额
- 可能存在未文档化的服务端限流（如 IP 级别）
- 建议集成时仍加保守限流：单股票间隔 200ms，批量场景加 500ms 间隔
- 新闻热榜在非交易日可能返回空数据

### 单次调用上限

| 接口 | 上限 | 说明 |
|------|------|------|
| `market info` | 1 只/次 | 不支持批量 |
| `market history` | 1 只/次 | 可指定天数 |
| `market fund` | 1 只/次 | 仅当日资金流 |
| `market ranking` | 80 条/次 | 超过 80 会截断 |
| `market related` | 1 只/次 | 关联板块 |
| `finance *` | 1 只/次 | 可指定期数 |
| `news hot_rank` | 1 页/次 | 可指定每页条数 |

## 3. 当前数据源使用现状

| 数据需求 | 当前来源 | 消耗者 |
|---------|---------|--------|
| 实时行情/价格 | 智兔 `get_single_realtime_quote()` | stock_utils, agent_utils |
| K线历史数据 | 智兔 `get_kline()` | data_source_manager, data_preheater |
| 财务指标(PE/PB/ROE) | 智兔 `get_comprehensive_financial_data()` | optimized_china_data |
| 技术指标(MACD/KDJ/BOLL) | 智兔 `get_macd/kdj/boll()` | data_preheater |
| 资金流向 | 智兔 `get_money_flow()` | zhitu_adapter |
| 公司简介/名称 | 智兔 `get_company_profile()` | agent_utils (情绪分析) |
| 指数行情 | 智兔 `get_market_overview()` | agent_utils (大盘概览) |
| 新闻/舆情搜索 | Tavily (MultiSearchClient 回退链) | agent_utils (情绪工具), news_analyst |

## 4. CICCWM 可替代的功能

| CICCWM 接口 | 替代目标 | 新增能力 |
|------------|---------|---------|
| `market info` | 智兔 `get_single_realtime_quote()` + `get_company_profile()` | PE/PB/ROE/市值/涨停价等一次返回 |
| `market history` | 智兔 `get_kline()` | — |
| `market fund` | 智兔 `get_money_flow()` | — |
| `market ranking` | 无 | 涨跌幅排行榜 |
| `market related` | 无 | 个股关联板块 |
| `finance indicators` | 智兔 `get_financial_indicators()` | 更多指标字段 |
| `finance income/cashflow/balance` | 无 | 利润表/现金流/资产负债表 |
| `news hot_rank` | Tavily 新闻搜索 | 中金专业热榜 |

## 5. 集成方案（3 个层次）

### 层次 1：创建 CICCWM 适配器

新建 `app/services/data_sources/ciccwm_adapter.py`，封装三个脚本的 Python 函数调用：

```python
class CiccwmAdapter:
    # 行情数据（替代智兔）
    def get_realtime_quote(code, market) -> dict    # market.info
    def get_kline(code, market, days) -> list        # market.history
    def get_fund_flow(code, market) -> dict           # market.fund
    def get_company_info(code, market) -> dict        # market.info (名称+简介)

    # 财务数据（替代+增强智兔）
    def get_financial_indicators(code) -> list        # finance.indicators
    def get_income_statement(code) -> list            # finance.income
    def get_cashflow(code) -> list                    # finance.cashflow
    def get_balance_sheet(code) -> list               # finance.balance

    # 新闻资讯（替代 Tavily）
    def get_hot_news(page_size=10) -> list            # news.hot_rank
```

### 层次 2：接入数据源优先级链

修改以下文件，将 CICCWM 插入优先级链（高于智兔）：

| 文件 | 修改内容 |
|------|---------|
| `tradingagents/constants/data_sources.py` | 新增 `DataSourceCode.CICCWM = "ciccwm"` |
| `tradingagents/dataflows/data_source_manager.py` | 在 `_get_zhitu_data()` 前加 `_get_ciccwm_data()`，优先级链变为 `MongoDB → CICCWM → 智兔 → AKShare → ...` |
| `tradingagents/dataflows/optimized_china_data.py` | 财务指标获取中，CICCWM 作为第一优先级（在 MongoDB 缓存之后） |
| `tradingagents/utils/stock_utils.py` | 实时价格获取中，CICCWM 作为第一优先级 |
| `pipeline/data_preheater.py` | K线和技术指标预热中，CICCWM 替代智兔 |

### 层次 3：替代 Tavily 新闻搜索

修改 `tradingagents/utils/search_client.py` 的 `MultiSearchClient`：

```
当前: BochaAI → Exa → SerpAPI → Tavily
改后: CICCWM热榜 → BochaAI → Exa → SerpAPI → Tavily
```

或者在 `agent_utils.py` 的情绪工具中，直接用 CICCWM 热榜 + 个股关联新闻替代 Tavily 搜索。

## 6. 股票代码映射

Pipeline 的股票代码格式是 `001335.SZ`，CICCWM 需要纯数字 + 市场代码：

| 后缀 | CICCWM market | 示例 |
|------|--------------|------|
| `.SZ` | `0` (深圳) | `001335.SZ` → `code=001335, market=0` |
| `.SH` | `1` (上海) | `600519.SH` → `code=600519, market=1` |
| `.BJ` | `2` (北交所) | `830799.BJ` → `code=830799, market=2` |
| 无前缀 `60/68` | `1` (上海) | 自动推断 |
| 无前缀 `00/30` | `0` (深圳) | 自动推断 |

需要在适配器中加一个 `normalize_code()` 函数做转换。

## 7. 预期效果

| 指标 | 改前 | 改后 |
|------|------|------|
| 智兔 API 调用 | 每只股票 ~8-10 次 | 降至 0（CICCWM 全覆盖）或仅技术指标回退 |
| Tavily 搜索 | 每只股票 1-2 次 | 降至 0（CICCWM 热榜替代） |
| 新增能力 | 无 | 利润表、现金流、资产负债表、涨跌幅排行、关联板块 |
| 数据质量 | 智兔免费 token 限速 | 中金专业数据，更稳定 |

## 8. 不动的部分

- **技术指标**（MACD/KDJ/BOLL）：CICCWM market skill 不提供技术指标计算，这部分仍由 MongoDB 缓存或智兔/AKShare 提供
- **Tavily 回退链**：保留 Tavily 作为最终兜底，只是优先级降低
