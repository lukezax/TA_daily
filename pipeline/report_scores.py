"""
报告分数解析模块
从 TradingAgents 生成的 Markdown 报告中提取结构化分数：
- 缠论趋势评分（czsc_report.md 中的 "综合评分：N/10"）
- 养家赢面（yangjia_report.md 中的 "赢面：70-75%" 等格式）

HTML 报告（report_generator.py）与飞书通知（feishu_notify.py）共用本模块，
保证两处展示的分数来源一致。
"""

import re
from pathlib import Path
from typing import Dict, Optional


# 缠论趋势评分：综合评分：4/10 / **综合评分**：3 分（满分 10 分） / 综合评分：5/10分 / 综合评分：4 分
CHAN_SCORE_RE = re.compile(
    r"综合评分[^：:\n]{0,4}[：:]\s*(\d{1,2})\s*(?:/\s*10)?\s*分?"
)

# 养家赢面（区间）：赢面：70-75% / 赢面评分：40-50% / **赢面评估：** ~72-75% / 当前赢面：约55-60%
WINRATE_RANGE_RE = re.compile(
    r"赢面[^：:\n]{0,8}[：:]\s*[*约~\s]*(\d{1,3})\s*%?\s*[-~至到]\s*(\d{1,3})\s*%?"
)

# 养家赢面（单值）：预估赢面: <60% / 赢面：约 58% / 赢面评估：~65% / 赢面：72%
WINRATE_SINGLE_RE = re.compile(
    r"赢面[^：:\n]{0,8}[：:]\s*[*约~\s]*(<)?\s*(\d{1,3})\s*%"
)

# 赢面无冒号的上限写法：赢面 < 50% / 赢面<60%
WINRATE_LT_RE = re.compile(
    r"赢面\s*[<＜]\s*(\d{1,3})\s*%"
)

# 赢面文字说明中出现 "70-75%"（如 "理由：赢面70-75%"），兜底提取
WINRATE_FREE_RE = re.compile(
    r"赢面\s*(\d{1,3})\s*[-~至到]\s*(\d{1,3})\s*%"
)


def parse_chan_score(md_text: str) -> Optional[int]:
    """从缠论报告文本解析趋势评分（1-10 整数）。未找到返回 None。"""
    if not md_text:
        return None
    m = CHAN_SCORE_RE.search(md_text)
    if not m:
        return None
    score = int(m.group(1))
    return max(1, min(10, score))


def parse_yangjia_winrate(md_text: str) -> Optional[Dict[str, int]]:
    """
    从养家报告文本解析赢面百分比。

    Returns:
        {"low": int, "high": int} 区间；单值 "<60%" 返回 {"low": 0, "high": 59}。
        未找到返回 None。
    """
    if not md_text:
        return None

    # 1) 区间格式：赢面：70-75%
    m = WINRATE_RANGE_RE.search(md_text)
    if m:
        low, high = int(m.group(1)), int(m.group(2))
        return {"low": min(low, high), "high": max(low, high)}

    # 2) 单值：预估赢面: <60%（上限） / 赢面：72%（精确值）
    m = WINRATE_SINGLE_RE.search(md_text)
    if m:
        value = int(m.group(2))
        if m.group(1):  # 带 < 前缀 → 上限
            return {"low": 0, "high": max(0, value - 1)}
        return {"low": value, "high": value}

    # 3) 无冒号上限：赢面 < 50% / 赢面<60%
    m = WINRATE_LT_RE.search(md_text)
    if m:
        value = int(m.group(1))
        return {"low": 0, "high": max(0, value - 1)}

    # 4) 自由文本兜底：赢面70-75%
    m = WINRATE_FREE_RE.search(md_text)
    if m:
        low, high = int(m.group(1)), int(m.group(2))
        return {"low": min(low, high), "high": max(low, high)}

    return None


def load_scores(
    results_dir: str, stock_code: str, date: str
) -> Dict[str, Optional[Dict[str, int]]]:
    """
    读取指定股票/日期的报告文件并解析分数。

    Args:
        results_dir: TradingAgents 结果根目录
        stock_code: 股票代码（支持 603889.SH 或 603889）
        date: 报告日期 YYYY-MM-DD

    Returns:
        {"chan_score": int|None, "yangjia_winrate": {"low","high"}|None}
    """
    base = Path(results_dir) / stock_code.split(".")[0] / date / "reports"

    chan_score: Optional[int] = None
    yangjia_winrate: Optional[Dict[str, int]] = None

    czsc_file = base / "czsc_report.md"
    if czsc_file.exists():
        try:
            chan_score = parse_chan_score(czsc_file.read_text(encoding="utf-8"))
        except (IOError, UnicodeDecodeError):
            chan_score = None

    yangjia_file = base / "yangjia_report.md"
    if yangjia_file.exists():
        try:
            yangjia_winrate = parse_yangjia_winrate(
                yangjia_file.read_text(encoding="utf-8")
            )
        except (IOError, UnicodeDecodeError):
            yangjia_winrate = None

    return {"chan_score": chan_score, "yangjia_winrate": yangjia_winrate}


def format_winrate(winrate: Optional[Dict[str, int]]) -> str:
    """将赢面 dict 格式化为展示文本："70-75%" / "<60%" / "—" """
    if not winrate:
        return "—"
    low, high = winrate.get("low"), winrate.get("high")
    if low is None or high is None:
        return "—"
    if low == 0:
        return f"<{high + 1}%"
    if low == high:
        return f"{low}%"
    return f"{low}-{high}%"
