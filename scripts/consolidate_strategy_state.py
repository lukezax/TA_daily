#!/usr/bin/env python3
"""把 strategy_wiki/insights 的多日结论汇总成「当前状态 + 待裁决假设」。

不调用 LLM、不拉取数据；只做关键词分类与极性统计，结果可复现。
建议每周执行一次，人工裁决后把结论写回 insight。
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI_DIR = ROOT / "strategy_wiki"

THEME_KEYWORDS = {
    "B1_3分有效性": ["B1_3分", "3分"],
    "B1评分体系": ["评分体系", "分数与收益", "高分", "倒挂"],
    "B2策略有效性": ["B2"],
    "B1通过率": ["通过率", "筛选标准"],
    "策略与市场脱钩": ["脱钩", "背离", "脱节", "普涨"],
    "数据质量": ["口径", "缓存", "未分类", "数据不一致"],
}

POSITIVE_WORDS = ["最优", "有效", "正收益", "优于", "正Alpha", "利好", "提升", "表现最好"]
NEGATIVE_WORDS = ["失效", "负收益", "负Alpha", "劣于", "反转", "倒挂", "严重恶化", "为负"]
CONCLUSION_RE = re.compile(r"^\s*(?:\d+[\.、)]|[-*])\s*(.+)$")


def extract_conclusions(text: str) -> list[str]:
    return [m.group(1).strip() for line in text.splitlines() if (m := CONCLUSION_RE.match(line))]


def classify(conclusion: str) -> list[str]:
    return [theme for theme, keywords in THEME_KEYWORDS.items() if any(k in conclusion for k in keywords)]


def polarity(conclusion: str) -> str:
    pos = any(w in conclusion for w in POSITIVE_WORDS)
    neg = any(w in conclusion for w in NEGATIVE_WORDS)
    if pos and not neg:
        return "正"
    if neg and not pos:
        return "负"
    return "中"


def build_state(insights: list[tuple[str, str]]) -> str:
    """insights: [(日期, 全文)]，按日期升序。"""
    by_theme: dict[str, dict] = defaultdict(lambda: {"正": [], "负": [], "中": [], "latest": ("", "")})
    for day, text in sorted(insights):
        for conclusion in extract_conclusions(text):
            for theme in classify(conclusion):
                entry = by_theme[theme]
                p = polarity(conclusion)
                entry[p].append((day, conclusion))
                entry["latest"] = (day, conclusion)

    contradictory = {
        theme: entry
        for theme, entry in by_theme.items()
        if entry["正"] and entry["负"]
    }

    lines = [
        "# 策略当前状态（自动生成，需人工裁决）",
        "",
        f"生成日期: {date.today().isoformat()}",
        "",
        "本文件由 `scripts/consolidate_strategy_state.py` 汇总 insights 生成，",
        "只做关键词与极性统计，**不代表结论正确**。裁决后请写回对应 insight 或 corrections。",
        "",
        "## 一、待人工裁决的矛盾主题",
        "",
    ]
    if contradictory:
        lines += ["| 主题 | 正面结论数 | 负面结论数 | 最新结论 |", "|------|-----------|-----------|---------|"]
        for theme, entry in sorted(contradictory.items()):
            latest_day, latest_text = entry["latest"]
            short = latest_text[:60].replace("|", "\\|")
            lines.append(
                f"| {theme} | {len(entry['正'])} | {len(entry['负'])} | {latest_day}: {short} |"
            )
    else:
        lines.append("（暂无被识别为矛盾的主题）")

    lines += ["", "## 二、已废弃/待复核假设", ""]
    if contradictory:
        for theme in sorted(contradictory):
            lines.append(f"- 【{theme}】同一主题出现正反两种结论，需回查样本量与数据口径后再决定是否保留。")
    else:
        lines.append("（暂无）")

    lines += ["", "## 三、最新洞察（最近10条）", ""]
    for day, text in sorted(insights, reverse=True)[:10]:
        conclusions = extract_conclusions(text)
        first = conclusions[0] if conclusions else text[:80]
        lines.append(f"- {day}: {first[:90]}")

    lines += [
        "",
        "## 四、裁决原则",
        "",
        "- 样本量 < 30 的结论不得用于判定策略失效或最优。",
        "- 先确认跨天验证数据口径（当前为 T+3，与主线 T+1 研判不同）。",
        "- 若新证据推翻旧结论，应在 corrections 中记录原因，而不是直接删除旧 insight。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    insights_dir = WIKI_DIR / "insights"
    insights = []
    for path in sorted(insights_dir.glob("*.md")):
        day = path.stem.replace("发现_", "")
        insights.append((day, path.read_text(encoding="utf-8")))
    output = WIKI_DIR / "current_state.md"
    output.write_text(build_state(insights), encoding="utf-8")
    print(f"已写入 {output}（汇总 {len(insights)} 条洞察）")


if __name__ == "__main__":
    main()
