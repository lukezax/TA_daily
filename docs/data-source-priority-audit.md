# TradingAgents-CN 数据源优先级审计报告

**日期**: 2026-06-11  
**问题背景**: 东方财富封 IP 导致 AKShare/Tushare 数据获取全线失败，分析任务大面积挂掉

---

## 一、数据源清单

### A股行情数据源

| 数据源 | 费用 | K线 | 实时行情 | 财务数据 | 新闻 | 股票列表 | 网络依赖 | 当前状态 |
|--------|------|-----|----------|----------|------|----------|----------|----------|
| **MongoDB** | 免费(本地) | ✅缓存 | ✅缓存 | ✅缓存 | ✅缓存 | N/A | 无 | ✅正常 |
| **Zhitu(智兔)** | 免费792次/天 + 付费兜底 | ✅ | ✅(单只) | ✅(PE/PB/ROE) | ❌ | ✅ | api.zhituapi.com(直连) | ✅正常 |
| **Tushare** | 付费(token) | ✅ | ✅ | ✅(完整) | ✅ | ✅ | api.tushare.pro(直连) | ⚠️tushare内部调东方财富也挂 |
| **AKShare** | 免费 | ✅ | ✅(全市场) | 部分 | ✅ | ✅ | **eastmoney.com**(被封!) | ❌挂了 |
| **BaoStock** | 免费 | ❌(adapter未实现) | ❌(adapter未实现) | ✅(仅PE/PB/PS) | ❌ | ✅ | baostock.com(直连) | ⚠️网络接收错误 |

### 新闻/搜索数据源

| 数据源 | 费用 | 用途 | 网络依赖 | 当前状态 |
|--------|------|------|----------|----------|
| **Tavily** | 付费(TAVILY_API_KEY) | A股情绪分析/策略研究搜索 | api.tavily.com(直连) | ✅正常 |
| **FinnHub** | 免费/付费 | 美股新闻(最高优先级) | finnhub.io | 未测试 |
| **Alpha Vantage** | 免费有限 | 美股新闻(第2优先级) | alphavantage.co | 未测试 |
| **NewsAPI** | 付费 | 新闻聚合(第3优先级) | newsapi.org | 未配置key |
| **东方财富新闻** | 免费 | A股新闻(Tavily的fallback) | eastmoney.com(被封!) | ❌挂了 |

---

## 二、当前优先级配置（问题分析）

### 数据库配置 (`system_configs.data_source_configs`)

| 优先级 | 数据源 | 市场 | 状态 |
|--------|--------|------|------|
| 10 | zhitu | a_shares | enabled |
| 3 | tushare | a_shares, hk_stocks | enabled |
| 2 | akshare | a_shares, hk_stocks | enabled |
| 1 | baostock | a_shares | enabled |

### 数据库配置 (`datasource_groupings`)

| 优先级 | 数据源 | 状态 |
|--------|--------|------|
| 10 | zhitu | enabled |
| 3 | Tushare | enabled |
| 2 | AKShare | enabled |
| 1 | baostock | enabled |

### 代码中的默认 fallback 顺序（刚改的）

| 位置 | 当前顺序 |
|------|----------|
| `data_source_manager.py` | zhitu → akshare → tushare → baostock |
| `mongodb_cache_adapter.py` | zhitu → tushare → akshare → baostock |
| `stock_validator.py` | zhitu → tushare → akshare → baostock |
| `app/services/data_sources/manager.py` | zhitu(10) → tushare(3) → akshare(2) → baostock(1) |

---

## 三、问题诊断

### 核心问题：东方财富封 IP

**影响范围**：
- AKShare **所有接口**底层都调 eastmoney.com → 全挂
- Tushare 的 `pro_bar()` 内部也调东方财富 → 报 `IOError: ERROR.`
- BaoStock 的网络连接也受影响 → `网络接收错误`
- **唯一不受影响的是 zhitu**（直连 api.zhituapi.com）和 **MongoDB 本地缓存**

### 当前 fallback 逻辑的问题

1. **`stock_validator._trigger_data_sync_async`**：之前只支持 tushare 和 akshare，没有 zhitu。（已修复但优先级不对）
2. **`data_source_manager.get_stock_data`**：之前没有 ZHITU 分支。（已修复但优先级不对）
3. **zhitu 被放在最高优先级**：但 zhitu 是付费的（虽然有免费额度），免费数据源应该优先

### 费用问题

- zhitu 免费额度：4 tokens × 198次/天 = **792次/天**
- 全量分析：24只股票 × ~3次API调用/只 = ~72次（够用）
- 全量筛选（stock项目）：3021只 × 3次/只 = ~9000次（远超免费额度，必须付费）
- **结论**：TradingAgents-CN 的分析任务（24只左右）免费额度够用；但如果改成 zhitu 最高优先级用于筛选，会快速耗尽免费额度

---

## 四、推荐优先级调整方案

### 原则
1. 免费数据源优先消耗（baostock/akshare/tushare）
2. zhitu 作为**兜底**（当免费源全挂时才用）
3. MongoDB 缓存永远最高优先级
4. BaoStock 虽免费但能力有限（只有股票列表和简单财务数据），不适合作为主力

### 推荐优先级

| 优先级 | 数据源 | 理由 |
|--------|--------|------|
| 最高(本地) | MongoDB 缓存 | 本地数据，零成本零延迟 |
| 4 | Tushare | 数据最全面，直连不依赖东方财富（`api.tushare.pro`），有付费token |
| 3 | AKShare | 免费但依赖东方财富网络，正常时很好用 |
| 2 | BaoStock | 完全免费，baostock.com直连，但能力弱（目前adapter K线未实现） |
| 1(兜底) | Zhitu | 直连可靠，免费额度有限，作为最后防线 |

### 但当前实际情况（东方财富被封）

东方财富被封时，实际可用的只有：
- MongoDB（缓存命中时）
- Tushare（**注意**：tushare pro_bar 内部也可能走东方财富，需要验证）
- Zhitu（直连正常）
- BaoStock（baostock.com直连，但当前网络接收错误可能是别的原因）

---

## 五、Tavily 使用情况

### 当前集成点

1. **`agent_utils.py` (情绪分析)**
   - A股/港股情绪分析的主数据源
   - 搜索查询：`"{ticker} {company_name} 最新消息 投资者情绪 股吧讨论"`
   - 30秒超时，失败后 fallback 到东方财富新闻
   - 会清除 SOCKS 代理环境变量再调用

2. **`strategy_researcher/tavily_client.py` (策略研究)**
   - 用于外部信息搜索
   - max_results=3，search_depth="basic"

### 费用
- Tavily API 按调用付费
- 每次分析任务调 1 次 Tavily（情绪分析阶段）
- 策略研究每天 1 次，约 3-4 个查询

---

## 六、待优化项

### P0（当前阻塞性问题）

1. **东方财富 IP 封禁**：需要确认是临时封禁还是永久封禁
   - 短期：设置 `NO_PROXY` 环境变量确保国内 API 不走代理
   - 中期：等待解封 / 换 IP
   - 长期：减少对东方财富的依赖

2. **Tushare 是否也受影响？** `tushare pro_bar()` 的数据来源需要确认——如果 tushare 后端也调东方财富，那它也不可靠

3. **BaoStock K线能力**：当前 `baostock_adapter.py` 的 `get_kline()` 返回 None（未实现）。BaoStock 本身支持历史K线（`bs.query_history_k_data_plus()`），应该实现

### P1（优先级调整）

4. **zhitu 优先级应该降低**：从 10 降到 1（兜底），tushare 设为最高（如果它不依赖东方财富的话）

5. **默认 fallback 顺序统一**：当前各处不一致（有的 zhitu 第一，有的 tushare 第一），应该全部统一

6. **`_trigger_data_sync_async` 中 BaoStock 可以参与同步**：它只是不支持"通过 sync_service 接口同步"，可以直接用 BaoStock API 获取数据写入 MongoDB

### P2（健壮性提升）

7. **NO_PROXY 配置**：在 TradingAgents-CN 的启动脚本中设置 `NO_PROXY=localhost,127.0.0.1,api.zhituapi.com,api.tushare.pro,baostock.com`，确保这些直连的API不走代理

8. **数据源健康检查**：启动时 ping 各数据源，自动跳过不可达的

9. **Tavily fallback 优化**：当东方财富挂了时，Tavily 的 fallback（东方财富新闻）也会挂，应该有其他 fallback

---

## 七、环境变量配置现状

```
TUSHARE_TOKEN=***  (已配置)
ZHITU_API_TOKEN=***  (已配置)
TAVILY_API_KEY=***  (已配置)
FINNHUB_API_KEY=***  (已配置)
ALPHA_VANTAGE_API_KEY=  (未配置)
NEWSAPI_KEY=  (未配置)
```

---

## 八、下一步行动建议

1. **先验证 Tushare 是否独立于东方财富**：直接测试 `tushare pro_bar()` 在当前网络下是否能用
2. **实现 BaoStock K线**：利用已有的 BaoStock 库实现 `get_kline()`
3. **调整优先级**：免费优先（tushare/baostock → akshare → zhitu 兜底）
4. **设置 NO_PROXY**：确保直连API不走被封的代理
5. **统一所有 fallback 顺序**
