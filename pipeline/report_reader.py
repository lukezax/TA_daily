"""
TradingAgents 报告读取器
读取 TradingAgents 已生成的报告文件（Markdown 格式）
"""

import re
from pathlib import Path
from typing import Dict, Optional


class TradingAgentsReportReader:
    """读取 TradingAgents 已生成的报告文件"""

    # 文件名到显示名称的映射
    REPORT_FILE_MAP = {
        "market_report.md": "市场技术分析",
        "fundamentals_report.md": "基本面分析",
        "news_report.md": "新闻分析",
        "sentiment_report.md": "社媒情绪分析",
        "czsc_report.md": "缠论结构分析",
        "yangjia_report.md": "养家视角分析",
        "investment_plan.md": "投资组合决策",
        "risk_management_decision.md": "风险管理裁决",
        "research_team_decision.md": "研究团队辩论",
        "trader_investment_plan.md": "交易员计划",
        "final_trade_decision.md": "最终投资决策",
    }

    def __init__(self, results_dir: str):
        self.results_dir = Path(results_dir)

    def _normalize_code(self, stock_code: str) -> str:
        """标准化股票代码，去除后缀（如 603296.SH -> 603296）"""
        return stock_code.split(".")[0]

    def get_report_path(self, stock_code: str, date: str) -> Optional[Path]:
        """获取指定股票和日期的报告目录 (results/{code}/{date}/reports/)"""
        code = self._normalize_code(stock_code)
        path = self.results_dir / code / date / "reports"
        return path if path.exists() else None

    def read_final_decision(self, stock_code: str, date: str) -> Optional[Dict]:
        """
        读取 final_trade_decision.md，解析出结构化数据

        Returns:
            Dict with keys: action, confidence, risk_score, target_price, summary
            或 None（文件不存在时）
        """
        path = self.get_report_path(stock_code, date)
        if not path:
            return None

        decision_file = path / "final_trade_decision.md"
        if not decision_file.exists():
            return None

        content = decision_file.read_text(encoding="utf-8")
        return self._parse_final_decision(content)

    def read_analyst_reports(self, stock_code: str, date: str) -> Dict[str, str]:
        """
        读取所有分析师报告的 Markdown 内容

        Returns:
            Dict[显示名称, Markdown内容]
        """
        path = self.get_report_path(stock_code, date)
        if not path:
            return {}

        reports = {}
        for filename, display_name in self.REPORT_FILE_MAP.items():
            file_path = path / filename
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if content.strip():
                        reports[display_name] = content
                except (IOError, UnicodeDecodeError):
                    continue

        return reports

    def _parse_final_decision(self, content: str) -> Dict:
        """
        从 final_trade_decision.md 解析结构化数据

        解析格式:
            ## 投资建议
            **行动**: 持有
            **置信度**: 70.0%
            **风险评分**: 50.0%
            **目标价位**: 113.97
            ## 分析推理
            {text}
        """
        result = {
            "action": "",
            "confidence": 0.0,
            "risk_score": 0.0,
            "target_price": 0.0,
            "summary": "",
        }

        # 解析行动
        action_match = re.search(r"\*\*行动\*\*[:：]\s*(.+)", content)
        if action_match:
            result["action"] = action_match.group(1).strip()

        # 解析置信度
        confidence_match = re.search(r"\*\*置信度\*\*[:：]\s*([\d.]+)", content)
        if confidence_match:
            result["confidence"] = float(confidence_match.group(1))

        # 解析风险评分
        risk_match = re.search(r"\*\*风险评分\*\*[:：]\s*([\d.]+)", content)
        if risk_match:
            result["risk_score"] = float(risk_match.group(1))

        # 解析目标价位
        target_match = re.search(r"\*\*目标价位\*\*[:：]\s*([\d.]+)", content)
        if target_match:
            result["target_price"] = float(target_match.group(1))

        # 解析分析推理（## 分析推理 之后的所有内容）
        summary_match = re.search(
            r"##\s*分析推理\s*\n+(.*)", content, re.DOTALL
        )
        if summary_match:
            result["summary"] = summary_match.group(1).strip()

        return result
