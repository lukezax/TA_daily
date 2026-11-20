# TradingAgents/graph/reflection.py

from typing import Dict, Any
from langchain_openai import ChatOpenAI

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


class Reflector:
    """Handles reflection on decisions and updating memory."""

    def __init__(self, quick_thinking_llm: ChatOpenAI):
        """Initialize the reflector with an LLM."""
        self.quick_thinking_llm = quick_thinking_llm
        self.reflection_system_prompt = self._get_reflection_prompt()

    def _get_reflection_prompt(self) -> str:
        """Get the system prompt for reflection."""
        return """
你是一位 T+1 研判复盘分析师。请基于真实收益复盘上一交易日的研判，输出中文、可迁移的经验。

严格遵循：
1. 判断对错：以 T+1 收盘价相对决策时价格的涨跌为准。「买入/关注」遇上涨为正确；「不要看」遇下跌或未上涨为正确。
2. 分析原因：从市场情报、技术指标、技术信号、价格走势、新闻、社媒情绪、基本面中找出决定性因素，并说明各因素权重。
3. 改进建议：针对误判提出可验证的修正方向（例如把某类信号由「关注」上调为「买入」），不要空泛。
4. 总结：提炼可复用的经验，并把它与相似情境联系起来。
5. 精简输出：把总结压成不超过 1000 token 的一句话，便于写入向量记忆。
6. 收益口径：收益为小数，0.05 表示 +5%；正数代表研判方向正确，负数代表错误，接近零代表影响很小。
7. 本系统只做研判、不实际下单：不要给出目标价、止损位或仓位建议。

所有输出必须使用中文，务必具体、可验证。你会同时收到来自价格走势、技术指标、新闻与情绪的客观市场描述作为背景。
"""

    def _extract_current_situation(self, current_state: Dict[str, Any]) -> str:
        """Extract the current market situation from the state.

        必须与 trader.py 查询记忆时拼接的文本口径一致（都含缠论），
        否则写入的向量与检索的向量会系统性偏差。
        """
        curr_market_report = current_state["market_report"]
        curr_sentiment_report = current_state["sentiment_report"]
        curr_news_report = current_state["news_report"]
        curr_fundamentals_report = current_state["fundamentals_report"]

        situation = f"{curr_market_report}\n\n{curr_sentiment_report}\n\n{curr_news_report}\n\n{curr_fundamentals_report}"

        czsc_report = current_state.get("czsc_report")
        if czsc_report:
            situation += f"\n\n缠论结构分析：\n{czsc_report}"

        return situation

    def _reflect_on_component(
        self, component_type: str, report: str, situation: str, returns_losses
    ) -> str:
        """Generate reflection for a component."""
        messages = [
            ("system", self.reflection_system_prompt),
            (
                "human",
                f"Returns: {returns_losses}\n\nAnalysis/Decision: {report}\n\nObjective Market Reports for Reference: {situation}",
            ),
        ]

        result = self.quick_thinking_llm.invoke(messages).content
        return result

    def reflect_bull_researcher(self, current_state, returns_losses, bull_memory):
        """Reflect on bull researcher's analysis and update memory."""
        situation = self._extract_current_situation(current_state)
        bull_debate_history = current_state["investment_debate_state"]["bull_history"]

        result = self._reflect_on_component(
            "BULL", bull_debate_history, situation, returns_losses
        )
        bull_memory.add_situations([(situation, result)])

    def reflect_bear_researcher(self, current_state, returns_losses, bear_memory):
        """Reflect on bear researcher's analysis and update memory."""
        situation = self._extract_current_situation(current_state)
        bear_debate_history = current_state["investment_debate_state"]["bear_history"]

        result = self._reflect_on_component(
            "BEAR", bear_debate_history, situation, returns_losses
        )
        bear_memory.add_situations([(situation, result)])

    def reflect_trader(self, current_state, returns_losses, trader_memory):
        """Reflect on trader's decision and update memory."""
        situation = self._extract_current_situation(current_state)
        trader_decision = current_state["trader_investment_plan"]

        result = self._reflect_on_component(
            "TRADER", trader_decision, situation, returns_losses
        )
        trader_memory.add_situations([(situation, result)])

    def reflect_invest_judge(self, current_state, returns_losses, invest_judge_memory):
        """Reflect on investment judge's decision and update memory."""
        situation = self._extract_current_situation(current_state)
        judge_decision = current_state["investment_debate_state"]["judge_decision"]

        result = self._reflect_on_component(
            "INVEST JUDGE", judge_decision, situation, returns_losses
        )
        invest_judge_memory.add_situations([(situation, result)])

    def reflect_risk_manager(self, current_state, returns_losses, risk_manager_memory):
        """Reflect on risk manager's decision and update memory."""
        situation = self._extract_current_situation(current_state)
        judge_decision = current_state["risk_debate_state"]["judge_decision"]

        result = self._reflect_on_component(
            "RISK JUDGE", judge_decision, situation, returns_losses
        )
        risk_manager_memory.add_situations([(situation, result)])
