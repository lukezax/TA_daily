"""
报告生成器
将筛选数据和分析结果渲染为响应式 HTML 页面
"""

import datetime
from pathlib import Path
from typing import Dict, Optional

import jinja2
import markdown

from pipeline.config import PipelineConfig
from pipeline.models import FilterResults, StockAnalysisResult
from pipeline.report_reader import TradingAgentsReportReader
from pipeline.report_scores import format_winrate, load_scores


class ReportGenerator:
    """HTML 报告生成器"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.report_reader = TradingAgentsReportReader(config.tradingagents_results_dir)
        self.template_dir = Path(__file__).parent / "templates"
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.template_dir)),
            autoescape=jinja2.select_autoescape(["html"]),
        )
        self.output_dir = Path(config.report_output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _md_to_html(self, md_text: str) -> str:
        """将 Markdown 文本转换为 HTML"""
        import re

        # 预处理：确保表格块前后有空行（markdown 表格需要前后空行才能正确解析）
        lines = md_text.split('\n')
        processed = []
        in_table = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            is_table_line = stripped.startswith('|') and stripped.endswith('|')

            if is_table_line and not in_table:
                # 表格开始，确保前面有空行
                if processed and processed[-1].strip() != '':
                    processed.append('')
                in_table = True
            elif not is_table_line and in_table:
                # 表格结束，确保后面有空行
                if stripped != '':
                    processed.append('')
                in_table = False

            processed.append(line)

        md_text = '\n'.join(processed)

        return markdown.markdown(
            md_text,
            extensions=["tables", "fenced_code", "sane_lists", "md_in_html"],
        )

    def _preprocess_report_content(self, report_name: str, content: str) -> str:
        """
        预处理报告内容，处理特殊格式（如 Python dict 字符串）

        以下文件可能保存为 Python dict 格式：
        - research_team_decision.md（研究团队辩论）
        - risk_management_decision.md（风险管理裁决）
        """
        import ast

        # 检测是否是 Python dict 格式
        stripped = content.strip()
        if not (stripped.startswith('{') and stripped.endswith('}')):
            return content

        # 尝试截断的 dict（末尾可能不完整）
        # 如果不以 } 结尾但以 { 开头，尝试补全
        if stripped.startswith('{') and not stripped.endswith('}'):
            # 截断的 dict，尝试找到最后一个完整的值
            stripped = stripped + "'}"  # 尝试补全

        try:
            data = ast.literal_eval(stripped)
            if not isinstance(data, dict):
                return content
        except (ValueError, SyntaxError):
            # 解析失败，可能是截断的 dict
            # 尝试提取可读内容：找到 'history': ' 或 'judge_decision': ' 后的文本
            result = self._extract_readable_from_raw_dict(content)
            return result if result else content

        # === 风险管理裁决 ===
        if "裁决" in report_name or "risk" in report_name.lower():
            return self._format_risk_decision(data)

        # === 研究团队辩论 ===
        if "辩论" in report_name or "research" in report_name.lower():
            return self._format_research_debate(data)

        # 其他 dict 格式文件：尝试通用格式化
        return self._format_generic_dict(data)

    def _format_risk_decision(self, data: dict) -> str:
        """格式化风险管理裁决的 dict 数据"""
        parts = []

        # 提取 judge_decision（最终裁决）
        judge = data.get('judge_decision', '')
        if judge:
            if '\\n' in judge:
                judge = judge.replace('\\n', '\n')
            parts.append(f"# 风险管理委员会裁决\n\n{judge}")

        # 提取各方辩论历史
        speaker_map = {
            'risky_history': '🔥 激进派',
            'safe_history': '🛡️ 保守派',
            'neutral_history': '⚖️ 中性派',
        }

        debate_parts = []
        for key, label in speaker_map.items():
            history = data.get(key, '')
            if history and len(history.strip()) > 10:
                if '\\n' in history:
                    history = history.replace('\\n', '\n')
                # 清理发言者前缀
                history = history.replace('Risky Analyst:', '').replace('Safe Analyst:', '').replace('Neutral Analyst:', '')
                debate_parts.append(f"### {label}\n\n{history.strip()}")

        if debate_parts:
            parts.append("---\n\n# 风控辩论记录\n\n" + "\n\n---\n\n".join(debate_parts))

        # 如果没有 judge_decision，尝试从 history 提取
        if not judge and data.get('history'):
            history = data['history']
            if '\\n' in history:
                history = history.replace('\\n', '\n')
            parts.append(f"# 风控辩论记录\n\n{history}")

        return '\n\n'.join(parts) if parts else str(data)[:2000]

    def _format_research_debate(self, data: dict) -> str:
        """格式化研究团队辩论的 dict 数据"""
        history = data.get('history', '')

        if '\\n' in history:
            history = history.replace('\\n', '\n')

        # 按发言者分段
        lines = history.split('\n')
        parts = []
        current_speaker = ""
        current_content = []

        for line in lines:
            if line.startswith('Bull Analyst:') or line.startswith('Bear Analyst:'):
                if current_speaker and current_content:
                    parts.append(f"### {current_speaker}\n\n" + '\n'.join(current_content))
                if line.startswith('Bull Analyst:'):
                    current_speaker = "🐂 看涨研究员"
                    current_content = [line.replace('Bull Analyst:', '').strip()]
                else:
                    current_speaker = "🐻 看跌研究员"
                    current_content = [line.replace('Bear Analyst:', '').strip()]
            else:
                current_content.append(line)

        if current_speaker and current_content:
            parts.append(f"### {current_speaker}\n\n" + '\n'.join(current_content))

        if parts:
            return "# 研究团队辩论记录\n\n" + "\n\n---\n\n".join(parts)
        elif history:
            return f"# 研究团队辩论记录\n\n{history}"
        else:
            return str(data)[:2000]

    def _format_generic_dict(self, data: dict) -> str:
        """通用 dict 格式化：提取所有有内容的字段"""
        parts = []
        for key, value in data.items():
            if isinstance(value, str) and len(value.strip()) > 20:
                clean_value = value.replace('\\n', '\n') if '\\n' in value else value
                parts.append(f"## {key}\n\n{clean_value}")
        return '\n\n---\n\n'.join(parts) if parts else str(data)[:2000]

    def _extract_readable_from_raw_dict(self, content: str) -> str:
        """从截断的 dict 字符串中提取可读内容"""
        import re

        # 尝试提取 judge_decision 的内容
        judge_match = re.search(r"'judge_decision':\s*'(.*?)(?:'(?:,|\s*}))", content, re.DOTALL)
        history_match = re.search(r"'history':\s*'(.*?)(?:'(?:,|\s*'[a-z]))", content, re.DOTALL)

        parts = []
        if judge_match:
            judge = judge_match.group(1).replace('\\n', '\n')
            parts.append(f"# 裁决\n\n{judge}")

        if history_match:
            history = history_match.group(1).replace('\\n', '\n')
            parts.append(f"# 辩论记录\n\n{history}")

        if parts:
            return '\n\n---\n\n'.join(parts)

        # 最后兜底：把整个内容当纯文本，替换 \n 为换行
        cleaned = content.replace('\\n', '\n').replace("{'", '').replace("'}", '')
        return cleaned[:5000]

    def generate(
        self,
        date: str,
        filter_data: FilterResults,
        analysis_data: Dict[str, StockAnalysisResult],
    ) -> Path:
        """
        生成每日报告 HTML 文件

        Args:
            date: 日期字符串 YYYY-MM-DD
            filter_data: 筛选结果
            analysis_data: AI 分析结果 {stock_code: StockAnalysisResult}

        Returns:
            生成的 HTML 文件路径
        """
        stocks = []

        for stock in filter_data.stocks:
            # 获取 AI 分析结果（可能为 None）
            analysis = analysis_data.get(stock.code)

            # 检查是否为校验失败的情况
            validation_failed = False
            if analysis and analysis.error_message and "修正均失败" in analysis.error_message:
                validation_failed = True

            # 读取分析师报告并转为 HTML
            analyst_reports_html = {}
            # 无论 analysis 状态如何，都尝试从文件系统读取报告（除非校验失败）
            if not validation_failed:
                raw_reports = self.report_reader.read_analyst_reports(stock.code, date)
                for report_name, md_content in raw_reports.items():
                    # 预处理：研究团队辩论文件可能是 Python dict 字符串格式
                    md_content = self._preprocess_report_content(report_name, md_content)
                    analyst_reports_html[report_name] = self._md_to_html(md_content)

            if validation_failed:
                # 校验失败：显示警告信息，不展示 AI 分析
                from pipeline.models import StockAnalysisResult
                analysis = StockAnalysisResult(
                    code=stock.code,
                    status="failed",
                    summary="⚠️ AI 分析数据校验未通过（模型多次生成错误的公司名称或价格），已放弃。仅展示 B1 策略筛选数据。",
                    error_message=analysis.error_message if analysis else "",
                )
            elif analysis and analysis.status == "completed":
                # 如果 analysis 缺少某些字段，尝试从文件系统补充
                if not analysis.recommendation or not analysis.summary:
                    decision = self.report_reader.read_final_decision(stock.code, date)
                    if decision:
                        if not analysis.recommendation:
                            analysis.recommendation = decision.get("action", "")
                        if not analysis.confidence_score:
                            analysis.confidence_score = decision.get("confidence", 0.0)
                        if not analysis.risk_score:
                            analysis.risk_score = decision.get("risk_score", 0.0)
                        if not analysis.target_price:
                            analysis.target_price = decision.get("target_price", 0.0)
                        if not analysis.summary:
                            analysis.summary = decision.get("summary", "")
            elif not analysis or analysis.status in ("failed", "timeout", "pending"):
                # 即使 API 没返回结果，也尝试从文件系统构建 analysis
                decision = self.report_reader.read_final_decision(stock.code, date)
                if decision and decision.get("action"):
                    from pipeline.models import StockAnalysisResult
                    analysis = StockAnalysisResult(
                        code=stock.code,
                        status="completed",
                        recommendation=decision.get("action", ""),
                        confidence_score=decision.get("confidence", 0.0),
                        risk_score=decision.get("risk_score", 0.0),
                        target_price=decision.get("target_price", 0.0),
                        summary=decision.get("summary", ""),
                    )

            # 将 analysis.summary 从 Markdown 转为 HTML
            if analysis and analysis.summary:
                analysis.summary = self._md_to_html(analysis.summary)

            # 生成同花顺个股页面链接
            pure_code = stock.code.split('.')[0]
            stock_url = f"https://stockpage.10jqka.com.cn/{pure_code}/"

            # 解析缠论评分与养家赢面（从报告文件提取，缺失时为 None）
            scores = load_scores(self.config.tradingagents_results_dir, stock.code, date)

            stocks.append(
                {
                    "code": stock.code,
                    "name": stock.name,
                    "exchange": stock.exchange,
                    "total_score": stock.total_score,
                    "tags": stock.tags,
                    "details": stock.details,
                    "analysis": analysis,
                    "analyst_reports": analyst_reports_html,
                    "url": stock_url,
                    "chan_score": scores["chan_score"],
                    "yangjia_winrate": scores["yangjia_winrate"],
                    "yangjia_winrate_str": format_winrate(scores["yangjia_winrate"]),
                }
            )

        # 排序：纯B2严格 > B2严格+宽松 > 纯B2宽松 > 缠高分 > B1按总分降序
        def _sort_priority(s):
            tags = s.get("tags", [])
            has_strict = 'B2严格' in tags
            has_loose = 'B2宽松' in tags
            if has_strict and not has_loose:
                priority = 400
            elif has_strict and has_loose:
                priority = 300
            elif has_loose:
                priority = 200
            elif '缠高分' in tags:
                priority = 100
            else:
                priority = 0
            return (-priority, -s["total_score"])

        stocks.sort(key=_sort_priority)

        template = self.env.get_template("report.html")
        html_content = template.render(
            date=date,
            total_scanned=filter_data.total_scanned,
            total_passed=filter_data.total_passed,
            stocks=stocks,
            now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        output_path = self.output_dir / f"{date}.html"
        output_path.write_text(html_content, encoding="utf-8")
        return output_path

    def generate_empty_report(self, date: str) -> Path:
        """
        生成无股票通过筛选时的报告

        Args:
            date: 日期字符串 YYYY-MM-DD

        Returns:
            生成的 HTML 文件路径
        """
        template = self.env.get_template("report.html")
        html_content = template.render(
            date=date,
            total_scanned=0,
            total_passed=0,
            stocks=[],
            now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        output_path = self.output_dir / f"{date}.html"
        output_path.write_text(html_content, encoding="utf-8")
        return output_path

    def generate_index(self) -> Path:
        """
        生成报告列表页（index.html）

        扫描报告输出目录，按日期倒序列出所有报告。

        Returns:
            生成的 index.html 文件路径
        """
        reports = []
        for html_file in sorted(self.output_dir.glob("*.html"), reverse=True):
            if html_file.name == "index.html":
                continue
            # 文件名格式: YYYY-MM-DD.html
            date_str = html_file.stem
            # 简单统计：读取文件中的 total_passed
            count = self._extract_count_from_report(html_file)
            reports.append(
                {
                    "date": date_str,
                    "count": count,
                    "url": f"./{date_str}.html",
                }
            )

        template = self.env.get_template("index.html")
        html_content = template.render(reports=reports)

        output_path = self.output_dir / "index.html"
        output_path.write_text(html_content, encoding="utf-8")
        return output_path

    def _extract_count_from_report(self, html_file: Path) -> int:
        """从已生成的报告 HTML 中提取通过数量"""
        try:
            content = html_file.read_text(encoding="utf-8")
            # 查找 "通过: X" 模式
            import re
            match = re.search(r"通过:\s*(\d+)", content)
            if match:
                return int(match.group(1))
        except (IOError, ValueError):
            pass
        return 0
