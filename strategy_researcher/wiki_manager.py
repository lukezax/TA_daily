"""Wiki 知识库管理 - 按 llm-wiki.md 模式管理 strategy_wiki/"""

import os
import logging
from pathlib import Path
from datetime import datetime, date

from strategy_researcher.config import RESEARCHER_CONFIG

logger = logging.getLogger("strategy_researcher.wiki")

WIKI_DIR = Path(RESEARCHER_CONFIG["wiki_dir"])


def init_wiki():
    """初始化 wiki 目录结构"""
    dirs = [
        WIKI_DIR,
        WIKI_DIR / "daily_reports",
        WIKI_DIR / "insights",
        WIKI_DIR / "experiments",
        WIKI_DIR / "recommendations",
        WIKI_DIR / "tracking",
        WIKI_DIR / "tracking" / "verified",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # CLAUDE.md - Schema
    claude_path = WIKI_DIR / "CLAUDE.md"
    if not claude_path.exists():
        claude_path.write_text(
            """# Strategy Wiki Schema

## 领域
A股量化筛选策略（B1波段 + B2放量反弹）的持续优化研究。

## 页面类型
- `daily_reports/YYYY-MM-DD.md` — 每日策略表现分析
- `insights/*.md` — 持久化的策略洞察（经过多日验证的发现）
- `experiments/*.md` — 优化实验记录（参数调整及其效果）
- `recommendations/*.md` — 待实施的优化建议

## 约定
- 所有数据引用标注来源：[来源: 文件名]
- 结论标注置信度：高/中/低
- 数字保留2位小数
- 日期格式：YYYY-MM-DD
""",
            encoding="utf-8",
        )

    # index.md
    index_path = WIKI_DIR / "index.md"
    if not index_path.exists():
        index_path.write_text("# Strategy Wiki Index\n\n（自动维护）\n", encoding="utf-8")

    # log.md
    log_path = WIKI_DIR / "log.md"
    if not log_path.exists():
        log_path.write_text("# Operation Log\n\n", encoding="utf-8")

    logger.info("Wiki 初始化完成: %s", WIKI_DIR)


class WikiManager:
    """Wiki 知识库读写"""

    def __init__(self):
        self.wiki_dir = WIKI_DIR
        init_wiki()

    def read_recent_context(self, days: int = None) -> str:
        """读取最近 N 天的报告 + insights，作为 LLM 上下文"""
        days = days or RESEARCHER_CONFIG["context_days"]
        parts = []

        # 最近的 daily reports
        reports_dir = self.wiki_dir / "daily_reports"
        if reports_dir.exists():
            report_files = sorted(reports_dir.glob("*.md"), reverse=True)[:days]
            for f in report_files:
                parts.append(f"## 历史报告: {f.stem}\n\n{f.read_text(encoding='utf-8')[:3000]}")

        # 所有 insights（通常不多）
        insights_dir = self.wiki_dir / "insights"
        if insights_dir.exists():
            for f in sorted(insights_dir.glob("*.md"))[-5:]:
                parts.append(f"## 洞察: {f.stem}\n\n{f.read_text(encoding='utf-8')[:1500]}")

        return "\n\n---\n\n".join(parts) if parts else "（暂无历史数据）"

    def write_daily_report(self, report_date: str, content: str):
        """写入每日报告"""
        path = self.wiki_dir / "daily_reports" / f"{report_date}.md"
        path.write_text(content, encoding="utf-8")
        self.append_log("daily_report", f"生成每日报告 {report_date}")
        self._update_index()
        logger.info("每日报告已写入: %s", path)

    def write_insight(self, title: str, content: str):
        """写入新洞察"""
        filename = title.replace(" ", "_").replace("/", "_")[:50]
        path = self.wiki_dir / "insights" / f"{filename}.md"
        full_content = f"# {title}\n\n创建日期: {date.today().isoformat()}\n\n{content}"
        path.write_text(full_content, encoding="utf-8")
        self.append_log("insight", title)
        self._update_index()
        logger.info("洞察已写入: %s", path)

    def write_recommendation(self, title: str, content: str):
        """写入优化建议"""
        filename = f"{date.today().isoformat()}_{title.replace(' ', '_')[:30]}"
        path = self.wiki_dir / "recommendations" / f"{filename}.md"
        full_content = f"# {title}\n\n日期: {date.today().isoformat()}\n\n{content}"
        path.write_text(full_content, encoding="utf-8")
        self.append_log("recommendation", title)
        self._update_index()
        logger.info("建议已写入: %s", path)

    def append_log(self, operation: str, title: str):
        """追加操作日志"""
        log_path = self.wiki_dir / "log.md"
        entry = f"## [{datetime.now().strftime('%Y-%m-%d %H:%M')}] {operation} | {title}\n\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def _update_index(self):
        """更新 index.md"""
        lines = ["# Strategy Wiki Index\n"]

        # Daily reports
        reports_dir = self.wiki_dir / "daily_reports"
        if reports_dir.exists():
            reports = sorted(reports_dir.glob("*.md"), reverse=True)[:10]
            lines.append("\n## 每日报告（最近10天）\n")
            for f in reports:
                lines.append(f"- [{f.stem}](daily_reports/{f.name})")

        # Insights
        insights_dir = self.wiki_dir / "insights"
        if insights_dir.exists():
            insights = sorted(insights_dir.glob("*.md"))
            if insights:
                lines.append("\n## 策略洞察\n")
                for f in insights:
                    lines.append(f"- [{f.stem}](insights/{f.name})")

        # Recommendations
        rec_dir = self.wiki_dir / "recommendations"
        if rec_dir.exists():
            recs = sorted(rec_dir.glob("*.md"), reverse=True)[:5]
            if recs:
                lines.append("\n## 优化建议（最近5条）\n")
                for f in recs:
                    lines.append(f"- [{f.stem}](recommendations/{f.name})")

        index_path = self.wiki_dir / "index.md"
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
