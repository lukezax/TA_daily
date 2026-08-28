"""策略研究员核心逻辑 - 收集数据 → 分析 → 生成报告"""

import json
import logging
from datetime import date, datetime

from strategy_researcher.data_collector import DataCollector
from strategy_researcher.cross_day_tracker import CrossDayTracker
from strategy_researcher.llm_client import LocalLLMClient
from strategy_researcher.tavily_client import TavilyClient
from strategy_researcher.wiki_manager import WikiManager

logger = logging.getLogger("strategy_researcher")


class StrategyResearcher:
    """每日执行的策略研究核心逻辑"""

    def __init__(self):
        self.collector = DataCollector()
        self.tracker = CrossDayTracker()
        self.llm = LocalLLMClient()
        self.tavily = TavilyClient()
        self.wiki = WikiManager()

    def run(self):
        """完整执行流程"""
        today = date.today().isoformat()
        logger.info("=" * 60)
        logger.info("策略研究员开始执行: %s", today)
        logger.info("=" * 60)

        # 1. 读取历史上下文
        logger.info("步骤1: 读取历史上下文...")
        context = self.wiki.read_recent_context()

        # 2. 收集今日数据
        logger.info("步骤2: 收集今日数据...")
        data = self.collector.collect_today()

        if not data.get("b1") and not data.get("b2"):
            logger.warning("无筛选数据，跳过分析")
            return

        # 3. 跨天收益验证
        logger.info("步骤3: 跨天收益验证...")
        self.tracker.verify_pending(data["current_prices"])
        performance = self.tracker.get_performance_summary()

        # 4. 记录今日信号
        logger.info("步骤4: 记录今日信号...")
        self.tracker.record_today_signals(data.get("b1"), data.get("b2"))

        # 5. LLM 分析（CoT）
        logger.info("步骤5: LLM 分析...")
        analysis_input = self._prepare_analysis_input(data, performance, context)
        analysis = self.llm.analyze_with_cot(
            data=analysis_input,
            question="分析今日策略表现，与历史对比，识别异常模式，提出优化方向。"
        )

        # 6. 如果需要外部信息，用 Tavily 搜索
        if analysis.get("needs_external_info"):
            logger.info("步骤6: 搜索外部信息（%d 个查询）...",
                        len(analysis["needs_external_info"]))
            external_info = []
            for query_item in analysis["needs_external_info"][:3]:  # 最多3个查询
                results = self.tavily.search(query_item["query"])
                external_info.append({
                    "query": query_item["query"],
                    "reason": query_item.get("reason", ""),
                    "results": results,
                })
            analysis["external_context"] = external_info

            # 如果有外部信息，让 LLM 结合外部信息补充分析
            if external_info:
                logger.info("步骤6b: 结合外部信息补充分析...")
                supplement = self._supplement_with_external(analysis, external_info)
                analysis["supplement"] = supplement
        else:
            logger.info("步骤6: 无需外部信息")

        # 7. 生成报告并写入 wiki
        logger.info("步骤7: 生成报告...")
        report = self._generate_report(today, data, performance, analysis)
        self.wiki.write_daily_report(today, report)

        # 8. 提取洞察和建议（如果有）
        self._extract_and_save_insights(analysis)

        logger.info("策略研究员执行完成")
        logger.info("  待验证信号: %d", self.tracker.get_pending_count())
        logger.info("=" * 60)

    def _prepare_analysis_input(self, data: dict, performance: dict, context: str) -> dict:
        """准备给 LLM 的分析输入（精简，避免超长）"""
        input_data = {}

        # B1 摘要
        if data.get("b1"):
            b1 = data["b1"]
            input_data["b1_today"] = {
                "文件": b1["filename"],
                "扫描总数": b1["total_scanned"],
                "通过数": b1["qualified_count"],
                "分数分布": b1["score_distribution"],
                "全市场平均涨幅": f"{b1['market_avg_change']}%",
                "全市场上涨比例": f"{b1['market_up_pct']}%",
            }

        # B2 摘要
        if data.get("b2"):
            b2 = data["b2"]
            input_data["b2_today"] = {
                "文件": b2["filename"],
                "严格通过": b2["strict_count"],
                "宽松通过": b2["loose_count"],
            }

        # 跨天收益
        if performance.get("total", 0) > 0:
            input_data["跨天收益验证"] = performance

        # 历史上下文（截断）
        if context and context != "（暂无历史数据）":
            input_data["历史上下文"] = context[:2000]

        return input_data

    def _supplement_with_external(self, analysis: dict, external_info: list) -> str:
        """结合外部信息补充分析"""
        info_text = ""
        for item in external_info:
            info_text += f"\n搜索: {item['query']}\n"
            for r in item.get("results", []):
                info_text += f"  - {r['title']}: {r['content'][:200]}\n"

        prompt = f"""基于以下外部信息，补充你之前的策略分析：

{info_text}

请简要说明这些信息对当前策略分析的启示（3-5句话）。"""

        return self.llm.chat(
            "你是量化策略研究员，请结合外部信息补充分析。",
            prompt,
        )

    def _generate_report(self, today: str, data: dict, performance: dict, analysis: dict) -> str:
        """生成每日报告"""
        lines = [f"# 策略日报 {today}\n"]

        # 一、今日筛选概况
        lines.append("## 一、今日筛选概况\n")
        if data.get("b1"):
            b1 = data["b1"]
            lines.append(f"- B1 通过: {b1['qualified_count']} 只")
            lines.append(f"  - 分数分布: {b1['score_distribution']}")
            lines.append(f"- 全市场平均涨幅: {b1['market_avg_change']}%")
            lines.append(f"- 全市场上涨比例: {b1['market_up_pct']}%")
        if data.get("b2"):
            b2 = data["b2"]
            lines.append(f"- B2 严格: {b2['strict_count']} 只, B2 宽松: {b2['loose_count']} 只")
        lines.append("")

        # 二、跨天收益验证
        lines.append("## 二、跨天收益验证\n")
        if performance.get("total", 0) > 0:
            if performance.get("overall"):
                o = performance["overall"]
                lines.append(f"- 总验证样本: {o['count']} 只")
                lines.append(f"- 整体平均收益: {o['avg_return']}%")
                lines.append(f"- 整体胜率: {o['win_rate']}%")
            if performance.get("by_strategy"):
                lines.append("\n| 策略 | 样本 | 平均收益 | 胜率 | 最大盈利 | 最大亏损 |")
                lines.append("|------|------|---------|------|---------|---------|")
                for key, stats in performance["by_strategy"].items():
                    lines.append(
                        f"| {key} | {stats['count']} | {stats['avg_return']}% | "
                        f"{stats['win_rate']}% | {stats['max_gain']}% | {stats['max_loss']}% |"
                    )
        else:
            lines.append("（暂无验证数据，需积累3天以上）")
        lines.append("")

        # 三、LLM 分析
        lines.append("## 三、策略分析\n")
        lines.append(analysis.get("raw_analysis", "（分析未完成）"))
        lines.append("")

        # 四、外部信息（如有）
        if analysis.get("external_context"):
            lines.append("## 四、外部信息参考\n")
            for item in analysis["external_context"]:
                lines.append(f"### 搜索: {item['query']}")
                lines.append(f"原因: {item.get('reason', '')}\n")
                for r in item.get("results", []):
                    lines.append(f"- **{r['title']}**: {r['content'][:200]}")
                lines.append("")
            if analysis.get("supplement"):
                lines.append("### 综合启示\n")
                lines.append(analysis["supplement"])
                lines.append("")

        # 五、待验证信号
        lines.append(f"## 五、状态\n")
        lines.append(f"- 待验证信号: {self.tracker.get_pending_count()} 只")
        lines.append(f"- 报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(lines)

    def _extract_and_save_insights(self, analysis: dict):
        """从分析中提取洞察和建议"""
        raw = analysis.get("raw_analysis", "")

        # 简单规则：如果分析中包含"置信度: 高"的结论，保存为 insight
        if "置信度: 高" in raw or "置信度：高" in raw:
            # 提取结论部分
            if "## 结论" in raw:
                conclusion = raw.split("## 结论")[1].split("##")[0].strip()
                if len(conclusion) > 50:
                    title = f"发现_{date.today().isoformat()}"
                    self.wiki.write_insight(title, conclusion)

        # 如果有优化方向，保存为 recommendation
        if "## 优化方向" in raw:
            opt_section = raw.split("## 优化方向")[1].split("##")[0].strip()
            if len(opt_section) > 50 and "数据不足" not in opt_section:
                title = f"优化建议_{date.today().isoformat()}"
                self.wiki.write_recommendation(title, opt_section)
