"""把 Mongo 里的历史报告装配成「要写进记忆的内容」。

这一层是纯函数：不碰网络、不碰数据库、不调 LLM。
它取代了原来让 LLM 生成「反思教训」的那一步 —— 改成用
「结构化决策 + 真实收益 + 当时的原始论证」直接拼出来。

抽取规则是拿 600 份历史样本实测选的（见 记忆写入实施方案.md）：
小标题不可靠（命名五花八门、`结论` 覆盖率仅 23~30%），
轮次标记可靠（600/600 份都是 2 轮），所以用「切末轮 + 末尾截断」。
"""
import re
from typing import Any, Dict, Optional

# 角色 -> Mongo 报告字段（与原生 reflection.py 的字段来源一一对应）
ROLE_FIELDS: Dict[str, str] = {
    "多方研究员": "bull_researcher",
    "空方研究员": "bear_researcher",
    "交易员": "trader_investment_plan",
    "研究总监": "research_team_decision",
    "风控": "risk_management_decision",
}

# 角色 -> 原生记忆集合名（与 trading_graph.py:597-601 一一对应）
ROLE_COLLECTIONS: Dict[str, str] = {
    "多方研究员": "bull_memory",
    "空方研究员": "bear_memory",
    "交易员": "trader_memory",
    "研究总监": "invest_judge_memory",
    "风控": "risk_manager_memory",
}

#: 单条记忆里「当时的论证」保留的字符数。
#: 实测 2000 字命中率 90~93%，3000 字只多 2 个点却让 prompt 胖一半。
MAX_ROLE_TEXT = 2000

#: 辩论稿的轮次分隔标记。每轮以 "Bull Analyst:" / "Bear Analyst:" 独立成行开头。
_ROUND_MARK = re.compile(r"^(Bull Analyst|Bear Analyst)\s*:", re.M)


def extract_role_text(reports: Optional[Dict], field: str, limit: int = MAX_ROLE_TEXT) -> str:
    """取某个角色「当时的论证」。

    辩论稿（bull/bear）只取最后一轮 —— 那是它听完对方反驳后的最终立场；
    其余角色（交易员/研究总监/风控）本身就是结论文档，整段使用。
    统一从末尾截断到 limit 字，因为结论总在结尾。
    """
    text = str((reports or {}).get(field) or "")
    if not text:
        return ""
    if field.endswith("_researcher"):
        marks = [m.start() for m in _ROUND_MARK.finditer(text)]
        if marks:
            text = text[marks[-1]:]
    return text[-limit:]


def compute_raw_change(price_at_decision: Optional[float], price_after: Optional[float]) -> Optional[float]:
    """原始涨跌幅（小数，0.1 表示 +10%），与买卖方向无关。

    买方研究员永远看涨、空方永远看跌，所以判他们谁对不能带方向，
    必须用这个原始涨跌。
    """
    if not price_at_decision or not price_after:
        return None
    if price_at_decision <= 0:
        return None
    return (price_after - price_at_decision) / price_at_decision


def is_correct(role: str, raw: Optional[float], pct: Optional[float]) -> Optional[bool]:
    """这个角色当时判对了没有。

    - 多方研究员：股价涨了就对
    - 空方研究员：股价跌了就对
    - 其余角色（交易员/研究总监/风控）：看带方向调整后的收益，
      买入见涨为对、卖出见跌为对

    数据缺失时返回 None（表示「未知」），不要和「判错」混为一谈。
    收益刚好为 0 算判错 —— 必须是 > 0。
    """
    if role == "多方研究员":
        return None if raw is None else raw > 0
    if role == "空方研究员":
        return None if raw is None else raw < 0
    return None if pct is None else pct > 0


def build_situation(reports: Optional[Dict]) -> str:
    """重建「当时的情境」，用于算向量。

    口径必须与 trader.py:40 查询记忆时、以及 reflection.py 的
    `_extract_current_situation` 逐字一致，否则写入的向量与检索的
    向量会有系统性偏差，相似的记忆反而检索不到。
    """
    if not reports:
        return ""
    reports = reports or {}
    parts = [
        str(reports.get("market_report") or ""),
        str(reports.get("sentiment_report") or ""),
        str(reports.get("news_report") or ""),
        str(reports.get("fundamentals_report") or ""),
    ]
    situation = "\n\n".join(parts)
    czsc = str(reports.get("czsc_report") or "")
    if czsc:
        situation += f"\n\n缠论结构分析：\n{czsc}"
    return situation


def build_recommendation(
    role: str,
    analysis_date: str,
    action: str,
    raw: Optional[float],
    pct: Optional[float],
    role_text: str,
) -> str:
    """拼出一条记忆里「给 agent 看」的那段文本。

    判对错取的是结构化字段算出来的 raw/pct，不依赖从散文里读立场 ——
    实测约 10% 的辩论稿末尾并没有明确写出买卖方向。
    """
    verdict = is_correct(role, raw, pct)
    verdict_str = "—" if verdict is None else ("✅正确" if verdict else "❌错误")
    pct_str = "—" if pct is None else f"{pct:+.2%}"
    return (
        f"【复盘 {analysis_date}｜同类情境】\n"
        f"系统决策：{action}｜实际结果：{pct_str}｜判断：{verdict_str}\n"
        f"我当时（{role}）的论证：\n{role_text}"
    )


__all__ = [
    "ROLE_FIELDS",
    "ROLE_COLLECTIONS",
    "MAX_ROLE_TEXT",
    "extract_role_text",
    "compute_raw_change",
    "is_correct",
    "build_situation",
    "build_recommendation",
]
