# 策略研究员 Agent 实施方案

## 一、目录结构

```
stock/
├── strategy_researcher/
│   ├── __init__.py
│   ├── main.py                 # 入口：调度 + 手动执行
│   ├── researcher.py           # 核心编排：收集 → 分析 → 输出
│   ├── data_collector.py       # 只读数据收集（CSV/报告/结果）
│   ├── cross_day_tracker.py    # 跨天收益追踪
│   ├── llm_client.py           # 本地 LLM 调用封装
│   ├── tavily_client.py        # Tavily 搜索封装
│   ├── wiki_manager.py         # Wiki 知识库读写
│   └── config.py               # 配置
│
├── strategy_wiki/              # 知识库（LLM 维护，人可读）
│   ├── CLAUDE.md               # Schema
│   ├── index.md                # 目录
│   ├── log.md                  # 操作日志
│   ├── daily_reports/          # 每日分析报告
│   ├── insights/               # 策略洞察（持久化的发现）
│   ├── experiments/            # 优化实验记录
│   └── recommendations/        # 待实施建议
```

---

## 二、各模块职责

### 2.1 `main.py` — 入口

```python
# 用法：
#   python -m strategy_researcher.main --run    # 立即执行 + 每交易日10:00调度
#   python -m strategy_researcher.main --now    # 立即执行一次
#   python -m strategy_researcher.main --init   # 初始化 wiki 目录结构
```

- APScheduler 定时调度，交易日 10:00 触发
- 交易日判断逻辑复用 pipeline 的 `_is_date_trading_day`
- `misfire_grace_time=60`

### 2.2 `data_collector.py` — 数据收集（只读）

负责从以下位置收集数据：

| 数据源 | 路径 | 收集内容 |
|--------|------|---------|
| B1 筛选 CSV | `reports/b1_filtered_*.csv` | 通过股票列表、各指标值、分数分布 |
| B2 筛选 CSV | `reports/b2_filtered_*.csv` | 严格/宽松通过列表、KDJ指标 |
| AI 分析报告 | `reports/YYYY-MM-DD.html` | 分析完成数/失败数 |
| TradingAgents 结果 | `TradingAgents-CN/results/{code}/{date}/` | 决策结果（买入/持有/卖出） |
| 跨天收益 | `strategy_wiki/tracking/` | 历史触发股票的后续表现 |

关键方法：
```python
class DataCollector:
    def get_latest_b1_csv() -> dict        # 最新B1筛选数据
    def get_latest_b2_csv() -> dict        # 最新B2筛选数据
    def get_b1_history(days=7) -> list     # 最近7天的B1数据
    def get_analysis_results(date) -> dict  # AI分析结果统计
    def get_market_overview(date) -> dict   # 全市场涨跌统计
```

### 2.3 `cross_day_tracker.py` — 跨天收益追踪

**这是最关键的模块**，解决"策略触发后实际表现如何"的问题。

```python
class CrossDayTracker:
    """
    每天记录触发的股票，N天后自动计算实际收益。
    
    存储：strategy_wiki/tracking/
    ├── pending.json          # 待验证的记录 [{code, buy_date, buy_price, strategy, score}]
    └── verified/
        ├── 2026-05-20.json   # 已验证的记录 [{..., sell_price, return_pct, hold_days}]
        └── ...
    """
    
    def record_today_signals(b1_results, b2_results):
        """记录今天触发的所有信号到 pending"""
        
    def verify_pending(current_prices):
        """检查 pending 中超过 N 天的记录，计算实际收益"""
        # 默认持有 3 天后验证
        # 从最新的 B1 CSV 中获取当前价格
        
    def get_performance_summary(days=30) -> dict:
        """汇总最近30天的策略表现"""
        # 返回：各策略/各分数段的平均收益、胜率、最大回撤
```

**数据流：**
```
每天 10:00:
  1. verify_pending() → 把到期的 pending 记录移到 verified/
  2. record_today_signals() → 把今天的筛选结果写入 pending
  3. get_performance_summary() → 供 researcher 分析
```

### 2.4 `llm_client.py` — 本地 LLM 调用

```python
class LocalLLMClient:
    """直接调用本地 llama.cpp (127.0.0.1:8080)"""
    
    def __init__(self, base_url="http://127.0.0.1:8080/v1", timeout=300):
        ...
    
    def chat(self, system_prompt, user_prompt, temperature=0.3) -> str:
        """单轮对话，返回文本"""
        # temperature=0.3 降低随机性，提高分析一致性
        
    def analyze_with_cot(self, data, question) -> dict:
        """CoT 分析：先列数据 → 推理 → 结论"""
        # 强制 LLM 按 "数据→推理→结论" 格式输出
        # 结论必须引用具体数字
```

### 2.5 `tavily_client.py` — 外部信息源

```python
class TavilyClient:
    """为策略分析提供外部知识输入（工具，非校验器）"""
    
    def search(self, query, max_results=3) -> list:
        """搜索并返回摘要"""
        
    def get_market_context(self) -> str:
        """搜索当前A股市场环境、风格轮动等宏观信息"""
        
    def get_strategy_knowledge(self, topic) -> str:
        """搜索特定策略/指标的优化经验和适用条件"""
```

**定位：信息源工具，不是校验器。**

使用场景：
- 市场环境判断：连续多天胜率异常低时，搜索近期市场动态
- 策略知识补充：发现某条件区分度下降时，搜索该指标的适用条件
- 板块信息：某类股票集中触发时，搜索相关板块近期动态

调用时机：
- 不是每天都调，由 researcher 的 LLM 自主决定是否需要外部信息
- 典型触发条件：连续3天胜率<20%、新发现的异常模式、策略参数需要调整时

### 2.6 `wiki_manager.py` — 知识库管理

```python
class WikiManager:
    """按 llm-wiki.md 模式管理 strategy_wiki/"""
    
    def init_wiki():
        """初始化目录结构和 CLAUDE.md"""
        
    def read_recent_context(days=3) -> str:
        """读取最近3天的报告 + insights，作为 LLM 上下文"""
        
    def write_daily_report(date, content):
        """写入每日报告"""
        
    def write_insight(title, content):
        """写入新发现的洞察"""
        
    def write_recommendation(title, content):
        """写入优化建议"""
        
    def update_index():
        """更新 index.md"""
        
    def append_log(operation, title):
        """追加操作日志"""
```

### 2.7 `researcher.py` — 核心编排

```python
class StrategyResearcher:
    """每日执行的核心逻辑"""
    
    def run(self):
        """完整执行流程"""
        # 1. 读取历史上下文
        context = self.wiki.read_recent_context(days=3)
        
        # 2. 收集今日数据
        data = self.collector.collect_today()
        
        # 3. 跨天收益验证
        self.tracker.verify_pending(data['current_prices'])
        performance = self.tracker.get_performance_summary()
        
        # 4. 记录今日信号
        self.tracker.record_today_signals(data['b1'], data['b2'])
        
        # 5. LLM 分析（CoT）
        analysis = self.llm.analyze_with_cot(
            data={
                'today_stats': data,
                'performance': performance,
                'history_context': context,
            },
            question="分析今日策略表现，识别异常模式，提出优化方向"
        )
        
        # 6. 如果需要外部信息，用 Tavily 搜索
        if analysis.get('needs_external_info'):
            for query in analysis['needs_external_info']:
                info = self.tavily.search(query['query'])
                analysis['external_context'] = analysis.get('external_context', [])
                analysis['external_context'].append({
                    'query': query['query'],
                    'reason': query['reason'],
                    'results': info,
                })
        
        # 7. 生成报告并写入 wiki
        report = self.generate_report(analysis, performance)
        self.wiki.write_daily_report(today, report)
        
        # 8. 如果有新洞察/建议，单独存储
        if analysis.get('new_insights'):
            for insight in analysis['new_insights']:
                self.wiki.write_insight(insight['title'], insight['content'])
        if analysis.get('recommendations'):
            for rec in analysis['recommendations']:
                self.wiki.write_recommendation(rec['title'], rec['content'])
```

---

## 三、每日报告模板

```markdown
# 策略日报 YYYY-MM-DD

## 一、今日筛选概况
- B1 通过: X 只（4分:X, 3分:X, 2分:X）
- B2 严格: X 只, B2 宽松: X 只
- 全市场平均涨幅: X%

## 二、跨天收益验证（核心指标）
| 策略 | 验证样本 | 平均收益 | 胜率 | 最大回撤 |
|------|---------|---------|------|---------|
| B1 4分 | X只 | X% | X% | X% |
| B1 3分 | X只 | X% | X% | X% |
| B2 严格 | X只 | X% | X% | X% |
| B2 宽松 | X只 | X% | X% | X% |

## 三、异常模式识别
- [数据] → [推理] → [结论]

## 四、优化假设（如有）
### 假设 1: ...
- 数据支撑: ...
- 外部信息（Tavily，如有）: ...
- 回测结果: ...
- 建议: ...

## 五、与历史对比
- 趋势变化: ...
- 累计洞察更新: ...
```

---

## 四、LLM Prompt 设计（幻觉抑制）

### System Prompt

```
你是一位量化策略研究员。你的职责是分析股票筛选策略的表现，识别问题，提出优化建议。

铁律：
1. 每个结论必须引用具体数据（哪个日期、哪个CSV、具体数字）
2. 不允许编造数据。如果数据不足，明确说"数据不足，无法判断"
3. 推理过程必须按 "数据 → 推理 → 结论" 格式
4. 优化建议必须附带可验证的预期效果（如"预期胜率从25%提升到40%"）
5. 区分"确定的发现"和"需要更多数据验证的假设"

输出格式要求：
- 用 markdown
- 数据引用格式：[数据来源: b1_filtered_20260528.csv]
- 结论标注置信度：高/中/低
```

### CoT 强制格式

```
请按以下格式分析：

## 数据
（列出所有相关数据点，标注来源）

## 推理
（基于数据的逻辑推导，每一步都要有依据）

## 结论
（明确的结论，标注置信度）

## 待验证
（需要更多数据才能确认的假设）
```

---

## 五、跨天收益追踪详细设计

### pending.json 格式

```json
[
  {
    "code": "002338.SZ",
    "name": "奥普光电",
    "buy_date": "2026-05-28",
    "buy_price": 60.27,
    "strategy": "B1",
    "score": 4,
    "tags": ["B1"],
    "hold_target_days": 3
  }
]
```

### verified/2026-05-28.json 格式

```json
[
  {
    "code": "002338.SZ",
    "name": "奥普光电",
    "buy_date": "2026-05-28",
    "buy_price": 60.27,
    "sell_date": "2026-06-02",
    "sell_price": 62.15,
    "hold_days": 3,
    "return_pct": 3.12,
    "strategy": "B1",
    "score": 4,
    "tags": ["B1"]
  }
]
```

### 价格获取方式

验证时需要获取"N天后的价格"。方案：
- 从最新的 `b1_filtered_*.csv` 中读取收盘价（该 CSV 包含所有扫描过的股票的收盘价）
- 如果 CSV 中没有（股票不在最新扫描范围内），调用 `get_stock_history_data(code, use_local=True)` 获取

---

## 六、配置

### `strategy_researcher/config.py`

```python
RESEARCHER_CONFIG = {
    # LLM
    'llm_base_url': 'http://127.0.0.1:8080/v1',
    'llm_model': 'local',
    'llm_timeout': 300,
    'llm_temperature': 0.3,
    
    # Tavily
    'tavily_api_key': 'tvly-dev-...',  # 从 .env 读取
    'tavily_max_results': 3,
    
    # 调度
    'schedule_time': '10:00',
    'hold_days': 3,  # 跨天验证的默认持有天数
    
    # Wiki
    'wiki_dir': 'strategy_wiki',
    'context_days': 3,  # 读取最近几天的报告作为上下文
    
    # 数据源
    'reports_dir': 'reports',
    'results_dir': 'TradingAgents-CN/results',
}
```

---

## 七、实施步骤

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 1 | 创建目录结构 + `config.py` | 无 |
| 2 | `wiki_manager.py` + 初始化 wiki | 步骤1 |
| 3 | `data_collector.py` | 步骤1 |
| 4 | `cross_day_tracker.py` | 步骤3 |
| 5 | `llm_client.py` | 步骤1 |
| 6 | `tavily_client.py` | 步骤1 |
| 7 | `researcher.py`（核心编排） | 步骤2-6 |
| 8 | `main.py`（入口+调度） | 步骤7 |
| 9 | 验证：手动执行一次，检查输出 | 步骤8 |

---

## 八、风险与约束

| 风险 | 缓解 |
|------|------|
| 本地 LLM 输出不稳定 | temperature=0.3 + 强制格式 + 结果校验 |
| 数据不足（刚开始几天） | 前3天只做统计，不做优化建议 |
| LLM 幻觉 | CoT + 数据引用 + 跨天实证数据 |
| 与 pipeline 资源争抢 | researcher 在 10:00 执行，pipeline 在 21:00，不冲突 |
| wiki 文件膨胀 | 每月归档旧的 daily_reports，只保留最近30天在线 |

---

## 九、第一版不做的事

- 不自动修改 filter.py 或任何策略代码
- 不做实时监控（只在 10:00 执行一次）
- 不做前端展示（直接看 markdown 文件）
- 不做多模型对比（只用本地 LLM）
- 不做自动回测（回测由人工确认后手动执行）
