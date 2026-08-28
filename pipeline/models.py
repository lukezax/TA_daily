"""
流水线数据模型定义
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class StockFilterData:
    """单只股票的筛选数据"""
    code: str           # 股票代码（如 603296.SH）
    name: str           # 股票名称
    exchange: str       # 交易所

    # 原始筛选结果标志
    result: bool        # 是否符合筛选条件

    # 筛选来源标签（一只股票可能同时满足多个策略）
    tags: List[str] = field(default_factory=list)  # ["B1", "B2严格", "B2宽松"]

    # 所有详细数据（保留原始 dict 结构，确保不丢失任何字段）
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_score(self) -> int:
        """新增条件总分"""
        return self.details.get("新增条件总分", 0)

    @property
    def close(self) -> float:
        return self.details.get("收盘价", 0)

    @property
    def change_pct(self) -> float:
        return self.details.get("涨幅", 0)

    @property
    def amplitude(self) -> float:
        return self.details.get("振幅", 0)


@dataclass
class FilterResults:
    """筛选结果集合"""
    date: str                           # YYYY-MM-DD
    total_scanned: int                  # 扫描总数
    stocks: List[StockFilterData]       # 符合条件的股票列表

    @property
    def total_passed(self) -> int:
        return len(self.stocks)


@dataclass
class StockAnalysisResult:
    """单只股票的 AI 分析结果"""
    code: str
    status: str = "pending"             # completed / failed / timeout / pending
    recommendation: str = ""            # 买入 / 卖出 / 持有
    confidence_score: float = 0.0       # 0-100
    risk_score: float = 0.0             # 0-100
    risk_level: str = ""                # 低 / 中 / 高
    target_price: float = 0.0           # 目标价位
    summary: str = ""                   # 分析推理摘要
    analyst_reports: Dict[str, str] = field(default_factory=dict)  # {报告名: markdown内容}
    execution_time: float = 0.0         # 执行耗时（秒）
    error_message: Optional[str] = None # 错误信息
    czsc_signals: Optional[Dict[str, Any]] = None  # 缠论结构化信号


@dataclass
class WorkerOutcome:
    """单只股 × 单 worker 的旁路结果(不进报告,仅日志/汇总)。"""
    code: str
    worker_name: str
    status: str                  # completed / failed / dead_skipped
    recommendation: str = ""
    confidence_score: float = 0.0
    risk_score: float = 0.0
    summary: str = ""
    error_message: str = ""
    execution_time: float = 0.0
    attempt: int = 0


@dataclass
class PipelineResult:
    """流水线执行结果"""
    date: str
    total_scanned: int
    total_filtered: int
    analysis_completed: int
    analysis_failed: int
    report_path: str
    success: bool = True
    error_message: Optional[str] = None
    primary_by: Dict[str, str] = field(default_factory=dict)   # {code: worker_name}
    extras: List[WorkerOutcome] = field(default_factory=list)  # 旁路记录
    dead_workers: List[str] = field(default_factory=list)      # 本轮失效的 worker
