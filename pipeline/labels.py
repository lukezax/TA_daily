"""T+1 研判三档标签（pipeline 侧）。

这里独立定义，不从 TradingAgents-CN 嵌套包导入：pipeline 的 CLI 直接从仓库根
运行时，TradingAgents-CN 不一定在 sys.path 上。tests/test_t1_decision_contract.py
会校验本文件与 tradingagents.decision_contract 的常量一致，防止漂移。
"""

LABELS = ("关注", "买入", "不要看")
LEGACY_LABEL_MAP = {"买入": "买入", "持有": "关注", "卖出": "不要看"}
