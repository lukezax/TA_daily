# CZSC（缠中说禅）项目分析与集成方案

## 一、项目概述

CZSC 是一个基于**缠中说禅理论**的量化技术分析框架，由 Rust + Python 混合架构实现。核心算法（分型、笔、中枢识别）用 Rust 编写，通过 PyO3 暴露给 Python，兼顾性能和易用性。

- **GitHub**: https://github.com/waditu/czsc
- **版本**: 1.0.X（Rust 重写版）
- **许可**: Apache-2.0
- **Python**: ≥ 3.10

---

## 二、核心功能

### 2.1 缠论核心算法

| 概念 | 说明 | 作用 |
|------|------|------|
| **分型（FX）** | K线的局部高低点 | 识别转折点 |
| **笔（BI）** | 分型之间的方向性运动 | 确定趋势方向 |
| **中枢（ZS）** | 价格震荡的区间 | 判断盘整/突破 |
| **多级别联立** | 日线+30分钟+5分钟联合分析 | 提高信号可靠性 |

### 2.2 信号系统

- 30+ 预置信号函数（K线形态、量价关系、OBV、压力位等）
- 信号逻辑组合：`signals_all`（与）、`signals_any`（或）、`signals_not`（非）
- 事件驱动：信号 → 事件 → 仓位 → 交易

### 2.3 回测与研究

- `CzscStrategyBase`：策略抽象基类
- `WeightBacktest`：基于权重序列的回测
- `run_research` / `run_replay`：研究与回放
- 输出：交易对、持仓序列、绩效指标

### 2.4 数据连接器

| 数据源 | 用途 |
|--------|------|
| Tushare | A股历史数据 |
| 天勤（TQSdk） | 期货实时/历史 |
| 聚宽（JoinQuant） | A股+期货 |
| CCXT | 加密货币 |

---

## 三、实现逻辑与流程

```
原始K线数据 (DataFrame)
    ↓ format_standard_kline()
List[RawBar]
    ↓ BarGenerator (多周期合成)
多级别K线 (日线 + 30分钟 + 5分钟)
    ↓ CZSC 核心算法 (Rust)
分型列表 → 笔列表 → 中枢列表
    ↓ Signal 信号函数 (30+)
信号序列 (Signal)
    ↓ Event 事件匹配
事件触发 (开仓/平仓条件满足)
    ↓ Position 仓位管理
交易决策 (买入/卖出/持有)
    ↓ CzscTrader 多级别联立
最终交易信号
```

---

## 四、优缺点分析

### 优点

1. **性能极高** — 核心算法 Rust 实现，处理大量K线数据毫秒级完成
2. **理论体系完整** — 缠论从分型到中枢到多级别联立，形成闭环
3. **信号丰富** — 30+ 预置信号函数，支持自定义组合
4. **多周期分析** — 自动合成多级别K线，联立决策
5. **回测完善** — 内置回测框架，支持参数优化
6. **社区活跃** — 飞书群、B站教程、持续更新

### 缺点

1. **学习曲线陡峭** — 缠论本身概念复杂，需要深入理解才能有效使用
2. **纯技术面** — 不考虑基本面、新闻、资金流向等因素
3. **依赖重** — 需要 Rust 工具链编译，依赖 TA-Lib（C库）
4. **信号滞后** — 缠论本质是事后确认（笔确认需要后续K线验证）
5. **参数敏感** — 不同参数组合产生不同的分型/笔划分，需要优化

---

## 五、对 Stock Pipeline 的可用之处

### 当前 Pipeline 架构

```
stock_filter.py (B1策略筛选)
    ↓ 筛选出候选股票
TradingAgents-CN (AI多Agent分析)
    ↓ 市场/基本面/新闻/情绪分析
Pipeline 报告生成
    ↓ HTML报告 + HTTP服务
```

### CZSC 可以补充的维度

| 当前能力 | CZSC 补充 | 价值 |
|---------|-----------|------|
| B1 策略只看 KDJ/均线 | 缠论分型/笔/中枢结构 | 更深层的市场结构判断 |
| TradingAgents 技术分析依赖 LLM 理解 | CZSC 产出精确的量化信号 | 消除 LLM 技术分析的不确定性 |
| 报告中技术分析是文字描述 | CZSC 产出具体的买卖点位 | 可操作性更强 |
| 无回测验证 | CZSC 内置回测 | 策略有效性可量化验证 |

### 具体可用场景

1. **筛选增强**：B1 筛选后，用 CZSC 判断候选股是否处于"买点"结构（一买/二买/三买）
2. **信号注入**：将 CZSC 的信号（如"日线一买"、"30分钟中枢突破"）作为结构化数据注入 TradingAgents 的分析上下文
3. **目标价计算**：基于中枢位置计算合理的目标价区间（中枢上沿/下沿）
4. **风险评估**：当前价格相对于笔和中枢的位置，量化风险等级
5. **报告可视化**：在报告中嵌入 CZSC 的K线图（带分型/笔/中枢标注）

---

## 六、集成方案

### 方案 A：轻量集成（推荐先做）

**只用 CZSC 的信号生成能力，不改变现有 Pipeline 架构。**

```python
# 在 pipeline 中新增一个模块: pipeline/czsc_analyzer.py

from czsc import CZSC, format_standard_kline, Freq, generate_czsc_signals

def analyze_stock_structure(code: str, kline_data: list) -> dict:
    """
    对单只股票进行缠论结构分析
    
    Returns:
        {
            "current_structure": "上涨笔中" / "下跌笔中" / "中枢震荡",
            "buy_signals": ["日线二买", "30分钟中枢突破"],
            "risk_level": "低" / "中" / "高",
            "support": 38.5,   # 支撑位（中枢下沿）
            "resistance": 42.0, # 阻力位（中枢上沿）
            "trend_score": 7,   # 趋势评分 1-10
        }
    """
```

**集成点**：
- 在 `pipeline/orchestrator.py` 中，B1 筛选后、提交 TradingAgents 前，调用 CZSC 分析
- 将 CZSC 结果作为额外字段写入报告
- 或将 CZSC 信号注入 TradingAgents 的 market_report 中

### 方案 B：深度集成

**将 CZSC 作为 TradingAgents 的一个独立分析师 Agent。**

```
TradingAgents 分析流程:
├── 市场分析师 (技术面 - K线/指标)
├── 基本面分析师 (PE/PB/ROE)
├── 新闻分析师 (新闻/公告)
├── 情绪分析师 (社交媒体)
├── 【新增】缠论分析师 (CZSC 信号)  ← 新 Agent
└── 交易员 (综合决策)
```

缠论分析师产出结构化的缠论分析报告，交给交易员综合判断。

### 方案 C：替代 B1 筛选

**用 CZSC 的信号系统替代或增强 stock_filter.py 的 B1 策略。**

```python
# 用缠论买点信号替代 KDJ<13 等条件
# 例如：日线一买 + 周线上涨趋势 = 强买入信号
```

---

## 七、集成后的优缺点

### 集成优点

1. **技术分析精确化** — 从 LLM 的模糊文字分析变为精确的量化信号
2. **买卖点明确** — 缠论的一买/二买/三买有明确的定义和位置
3. **风险可量化** — 基于中枢位置计算止损/止盈
4. **多维度验证** — AI 分析 + 缠论信号交叉验证，提高决策可靠性
5. **回测支撑** — 可以量化验证策略历史表现

### 集成缺点

1. **增加复杂度** — 系统多了一个分析维度，维护成本增加
2. **依赖重** — CZSC 需要 Rust 编译环境 + TA-Lib C 库
3. **信号冲突** — 缠论信号可能与 AI 分析结论矛盾，需要冲突解决机制
4. **数据需求** — 缠论需要较长的历史K线（至少 120 根以上才能形成有效的笔和中枢）
5. **实时性** — 缠论信号有确认滞后（笔需要后续K线确认），不适合日内超短线
6. **学习成本** — 团队需要理解缠论才能有效调参和排错

---

## 八、推荐实施路径

```
阶段 1（1-2天）：安装 CZSC，验证基本功能
    pip install czsc
    用智兔 K线数据跑一只股票的缠论分析，确认输出

阶段 2（2-3天）：轻量集成（方案 A）
    新增 pipeline/czsc_analyzer.py
    B1 筛选后对候选股做缠论结构分析
    将结果写入报告的"技术结构"字段

阶段 3（可选）：深度集成（方案 B）
    在 TradingAgents 中新增缠论分析师 Agent
    将 CZSC 信号作为结构化数据注入 LLM 上下文

阶段 4（可选）：策略优化（方案 C）
    用 CZSC 回测框架验证 B1 策略的历史表现
    基于回测结果优化筛选条件
```

---

## 九、数据流对接

CZSC 需要的输入数据格式：

```python
# DataFrame 格式
columns = ['dt', 'open', 'close', 'high', 'low', 'vol', 'amount']
# dt: datetime, 其他: float

# 或 RawBar 格式
RawBar(symbol="000001", dt=datetime, open=10.5, close=10.8, 
       high=11.0, low=10.3, vol=1000000, amount=10500000)
```

**与智兔 API 的对接**：智兔的 `get_kline()` 返回的数据可以直接转换为 CZSC 需要的格式：

```python
# 智兔 K线 → CZSC RawBar
zhitu_kline = zhitu.get_kline(code, period='d', limit=250)
bars = [
    RawBar(symbol=code, dt=parse(item['time']), 
           open=item['open'], close=item['close'],
           high=item['high'], low=item['low'],
           vol=item['volume'], amount=item['amount'] or 0)
    for item in zhitu_kline
]
czsc_obj = CZSC(bars)
```

---

## 十、结论

CZSC 是一个成熟的缠论量化框架，与当前 Pipeline 的互补性很强：

- **B1 策略**负责"选什么股"（筛选）
- **CZSC**负责"什么时候买"（择时）
- **TradingAgents**负责"综合判断"（决策）

三者结合可以形成"选股 → 择时 → 决策"的完整闭环。建议从方案 A（轻量集成）开始，验证效果后再决定是否深度集成。
