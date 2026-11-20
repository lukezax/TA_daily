import functools
import time
import json
import re

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
from tradingagents.agents.utils.instrument_utils import build_instrument_context
from tradingagents.decision_contract import T1_DECISION_RULE
logger = get_logger("default")


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        # 使用统一的股票类型检测
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(company_name)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        # 根据股票类型确定货币单位
        currency = market_info['currency_name']
        currency_symbol = market_info['currency_symbol']

        logger.debug(f"💰 [DEBUG] ===== 交易员节点开始 =====")
        logger.debug(f"💰 [DEBUG] 交易员检测股票类型: {company_name} -> {market_info['market_name']}, 货币: {currency}")
        logger.debug(f"💰 [DEBUG] 货币符号: {currency_symbol}")
        logger.debug(f"💰 [DEBUG] 市场详情: 中国A股={is_china}, 港股={is_hk}, 美股={is_us}")
        logger.debug(f"💰 [DEBUG] 基本面报告长度: {len(fundamentals_report)}")
        logger.debug(f"💰 [DEBUG] 基本面报告前200字符: {fundamentals_report[:200]}...")

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"

        # 缠论结构分析（如果可用）
        czsc_report = state.get("czsc_report", "")
        if czsc_report:
            curr_situation += f"\n\n缠论结构分析：\n{czsc_report}"

        # 检查memory是否可用
        if memory is not None:
            logger.warning(f"⚠️ [DEBUG] memory可用，获取历史记忆")
            past_memories = memory.get_memories(curr_situation, n_matches=2)
            past_memory_str = ""
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            logger.warning(f"⚠️ [DEBUG] memory为None，跳过历史记忆检索")
            past_memories = []
            past_memory_str = "暂无历史记忆数据可参考。"

        # Extract ground truth from market_report (tool-verified data)
        correct_name = company_name  # fallback to code
        correct_price = "未知"
        if market_research_report:
            title_match = re.search(r'\*\*(.+?)（\d{6}）', market_research_report)
            if title_match:
                correct_name = title_match.group(1)

        # 使用统一的价格提取工具（增强正则 + 数据源 fallback）
        from tradingagents.utils.stock_utils import extract_price_with_fallback
        correct_price = extract_price_with_fallback(company_name, market_research_report)

        context = {
            "role": "user",
            "content": f"Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {company_name}. This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment. Use this plan as a foundation for evaluating your next trading decision.\n\nProposed Investment Plan: {investment_plan}\n\nLeverage these insights to make an informed and strategic decision.",
        }

        messages = [
            {
                "role": "system",
                "content": f"""您是一位 T+1 研判助理，基于团队分析给出下一交易日的方向研判与关注等级。
{T1_DECISION_RULE}

📌 关键事实（来自实时行情工具验证，不可更改）：
- 公司名称：{correct_name}
- 股票代码：{company_name}
- 当前价格：¥{correct_price}
请确保你的分析严格基于以上事实，不要使用其他公司名称或价格。

⚠️ 重要提醒：当前分析的股票代码是 {company_name}，请使用正确的货币单位：{currency}（{currency_symbol}）
{instrument_context}

🔴 严格要求：
- 公司名称必须严格按照基本面报告中的真实数据
- 绝对禁止使用错误的公司名称或混淆不同的股票
- 所有分析必须基于提供的真实数据，不允许假设或编造

请在您的分析中包含以下关键信息：
1. **T+1 方向**: 涨 / 跌 / 震荡
2. **关注等级**: 关注 / 买入 / 不要看
3. **置信度**: 对研判的信心程度(0-1之间)
4. **风险评分**: 研判风险等级(0-1之间，0为低风险，1为高风险)
5. **详细推理**: 支持研判的具体理由

不要输出目标价、止损位或仓位比例；这些不是本系统的输出项。

请用中文撰写分析内容，并始终以'研判结论: **关注/买入/不要看**'结束您的回应。

请不要忘记利用过去决策的经验教训来避免重复错误。以下是类似情况下的反思和经验教训: {past_memory_str}""",
            },
            context,
        ]

        logger.debug(f"💰 [DEBUG] 准备调用LLM，系统提示包含货币: {currency}")
        logger.debug(f"💰 [DEBUG] 系统提示中的关键部分: 目标价格({currency})")

        result = llm.invoke(messages)

        logger.debug(f"💰 [DEBUG] LLM调用完成")
        logger.debug(f"💰 [DEBUG] 交易员回复长度: {len(result.content)}")
        logger.debug(f"💰 [DEBUG] 交易员回复前500字符: {result.content[:500]}...")
        logger.debug(f"💰 [DEBUG] ===== 交易员节点结束 =====")

        return {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
