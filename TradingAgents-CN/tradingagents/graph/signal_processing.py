# TradingAgents/graph/signal_processing.py

from langchain_openai import ChatOpenAI

# 导入统一日志系统和图处理模块日志装饰器
from tradingagents.decision_contract import LABELS, LEGACY_LABEL_MAP
from tradingagents.utils.logging_init import get_logger
from tradingagents.utils.tool_logging import log_graph_module
logger = get_logger("graph.signal_processing")


class SignalProcessor:
    """Processes trading signals to extract actionable decisions."""

    def __init__(self, quick_thinking_llm: ChatOpenAI):
        """Initialize with an LLM for processing."""
        self.quick_thinking_llm = quick_thinking_llm

    @log_graph_module("signal_processing")
    def process_signal(self, full_signal: str, stock_symbol: str = None) -> dict:
        """
        Process a full trading signal to extract structured decision information.

        Args:
            full_signal: Complete trading signal text
            stock_symbol: Stock symbol to determine currency type

        Returns:
            Dictionary containing extracted decision information
        """

        # 验证输入参数
        if not full_signal or not isinstance(full_signal, str) or len(full_signal.strip()) == 0:
            logger.error(f"❌ [SignalProcessor] 输入信号为空或无效: {repr(full_signal)}")
            return {
                'action': '关注',
                'direction': '震荡',
                'target_price': None,
                'confidence': 0.5,
                'risk_score': 0.5,
                'reasoning': '输入信号无效，默认关注（不买入）'
            }

        # 清理和验证信号内容
        full_signal = full_signal.strip()
        if len(full_signal) == 0:
            logger.error(f"❌ [SignalProcessor] 信号内容为空")
            return {
                'action': '关注',
                'direction': '震荡',
                'target_price': None,
                'confidence': 0.5,
                'risk_score': 0.5,
                'reasoning': '信号内容为空，默认关注（不买入）'
            }

        # 检测股票类型和货币
        from tradingagents.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_symbol)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        currency = market_info['currency_name']
        currency_symbol = market_info['currency_symbol']

        logger.info(f"🔍 [SignalProcessor] 处理信号: 股票={stock_symbol}, 市场={market_info['market_name']}, 货币={currency}",
                   extra={'stock_symbol': stock_symbol, 'market': market_info['market_name'], 'currency': currency})

        messages = [
            (
                "system",
                f"""您是一位专业的金融分析助手，负责从研判报告中提取结构化的 T+1 研判结论。

请从提供的分析报告中提取以下信息，并以JSON格式返回：

{{
    "action": "关注/买入/不要看",
    "direction": "涨/跌/震荡",
    "target_price": 数字或null（可选，仅当报告中明确给出时填写；非必需）,
    "confidence": 数字(0-1之间，如果没有明确提及则为0.7),
    "risk_score": 数字(0-1之间，如果没有明确提及则为0.5),
    "reasoning": "研判的主要理由摘要"
}}

请确保：
1. action字段必须是"关注"、"买入"或"不要看"之一（这是关注等级，不是交易指令；绝对不允许使用英文buy/hold/sell）
2. direction字段必须是"涨"、"跌"或"震荡"之一，表示 T+1 方向研判
3. target_price 不是必需项；原报告没有明确目标价时填 null，不要编造
4. confidence和risk_score应该在0-1之间
5. reasoning应该是简洁的中文摘要
6. 所有内容必须使用中文，不允许任何英文投资建议

特别注意：
- 股票代码 {stock_symbol or '未知'} 是{market_info['market_name']}，使用{currency}计价
- 只提取研判结论，不要生成目标价、止损位或仓位建议

如果某些信息在报告中没有明确提及，请使用合理的默认值。""",
            ),
            ("human", full_signal),
        ]

        # 验证messages内容
        if not messages or len(messages) == 0:
            logger.error(f"❌ [SignalProcessor] messages为空")
            return self._get_default_decision()
        
        # 验证human消息内容
        human_content = messages[1][1] if len(messages) > 1 else ""
        if not human_content or len(human_content.strip()) == 0:
            logger.error(f"❌ [SignalProcessor] human消息内容为空")
            return self._get_default_decision()

        logger.debug(f"🔍 [SignalProcessor] 准备调用LLM，消息数量: {len(messages)}, 信号长度: {len(full_signal)}")

        try:
            response = self.quick_thinking_llm.invoke(messages).content
            logger.debug(f"🔍 [SignalProcessor] LLM响应: {response[:200]}...")

            # 尝试解析JSON响应
            import json
            import re

            # 提取JSON部分
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_text = json_match.group()
                logger.debug(f"🔍 [SignalProcessor] 提取的JSON: {json_text}")
                decision_data = json.loads(json_text)

                # 验证和标准化数据：新三档为权威，旧标签仅做兼容映射
                action = decision_data.get('action', '关注')
                if action not in LABELS:
                    action_map = {
                        **LEGACY_LABEL_MAP,
                        'buy': '买入', 'BUY': '买入', '购买': '买入', 'purchase': '买入',
                        'hold': '关注', 'HOLD': '关注', '保持': '关注', 'keep': '关注',
                        'sell': '不要看', 'SELL': '不要看', '出售': '不要看', 'dispose': '不要看',
                    }
                    action = action_map.get(action, '关注')
                    if action != decision_data.get('action', '关注'):
                        logger.debug(f"🔍 [SignalProcessor] 关注等级映射: {decision_data.get('action')} -> {action}")

                # 目标价不是本系统的输出项：只在报告明确给出时保留，不从正文猜测
                target_price = decision_data.get('target_price')
                if target_price is None or target_price == "null" or target_price == "":
                    target_price = None
                else:
                    # 确保价格是数值类型
                    try:
                        if isinstance(target_price, str):
                            # 清理字符串格式的价格
                            clean_price = target_price.replace('$', '').replace('¥', '').replace('￥', '').replace('元', '').replace('美元', '').strip()
                            target_price = float(clean_price) if clean_price and clean_price.lower() not in ['none', 'null', ''] else None
                        elif isinstance(target_price, (int, float)):
                            target_price = float(target_price)
                        logger.debug(f"🔍 [SignalProcessor] 处理后的目标价格: {target_price}")
                    except (ValueError, TypeError):
                        target_price = None
                        logger.warning(f"🔍 [SignalProcessor] 价格转换失败，设置为None")

                direction = str(decision_data.get('direction', '')).strip()
                if direction not in ('涨', '跌', '震荡'):
                    direction = '震荡'

                result = {
                    'action': action,
                    'direction': direction,
                    'target_price': target_price,
                    'confidence': float(decision_data.get('confidence', 0.7)),
                    'risk_score': float(decision_data.get('risk_score', 0.5)),
                    'reasoning': decision_data.get('reasoning', '基于综合分析的 T+1 研判')
                }
                logger.info(f"🔍 [SignalProcessor] 处理结果: {result}",
                           extra={'action': result['action'], 'target_price': result['target_price'],
                                 'confidence': result['confidence'], 'stock_symbol': stock_symbol})
                return result
            else:
                # 如果无法解析JSON，使用简单的文本提取
                return self._extract_simple_decision(response)

        except Exception as e:
            logger.error(f"信号处理错误: {e}", exc_info=True, extra={'stock_symbol': stock_symbol})
            # 回退到简单提取
            return self._extract_simple_decision(full_signal)

    def _smart_price_estimation(self, text: str, action: str, is_china: bool) -> float:
        """智能价格推算方法"""
        import re
        
        # 尝试从文本中提取当前价格和涨跌幅信息
        current_price = None
        percentage_change = None
        
        # 提取当前价格
        current_price_patterns = [
            r'当前价[格位]?[：:]?\s*[¥\$]?(\d+(?:\.\d+)?)',
            r'现价[：:]?\s*[¥\$]?(\d+(?:\.\d+)?)',
            r'股价[：:]?\s*[¥\$]?(\d+(?:\.\d+)?)',
            r'价格[：:]?\s*[¥\$]?(\d+(?:\.\d+)?)',
        ]
        
        for pattern in current_price_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    current_price = float(match.group(1))
                    break
                except ValueError:
                    continue
        
        # 提取涨跌幅信息
        percentage_patterns = [
            r'上涨\s*(\d+(?:\.\d+)?)%',
            r'涨幅\s*(\d+(?:\.\d+)?)%',
            r'增长\s*(\d+(?:\.\d+)?)%',
            r'(\d+(?:\.\d+)?)%\s*的?上涨',
        ]
        
        for pattern in percentage_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    percentage_change = float(match.group(1)) / 100
                    break
                except ValueError:
                    continue
        
        # 基于动作和信息推算目标价
        if current_price and percentage_change:
            if action == '买入':
                return round(current_price * (1 + percentage_change), 2)
            elif action == '卖出':
                return round(current_price * (1 - percentage_change), 2)
        
        # 如果有当前价格但没有涨跌幅，使用默认估算
        if current_price:
            if action == '买入':
                # 买入建议默认10-20%涨幅
                multiplier = 1.15 if is_china else 1.12
                return round(current_price * multiplier, 2)
            elif action == '卖出':
                # 卖出建议默认5-10%跌幅
                multiplier = 0.95 if is_china else 0.92
                return round(current_price * multiplier, 2)
            else:  # 持有
                # 持有建议使用当前价格
                return current_price
        
        return None

    def _extract_simple_decision(self, text: str) -> dict:
        """简单的决策提取方法作为备用"""
        import re

        # 提取关注等级：新三档优先，旧标签/英文仅兼容
        action = '关注'
        if re.search(r'不要看|不看|SELL', text, re.IGNORECASE):
            action = '不要看'
        elif re.search(r'买入|BUY', text, re.IGNORECASE):
            action = '买入'
        elif re.search(r'关注|WATCH', text, re.IGNORECASE):
            action = '关注'

        return {
            'action': action,
            'direction': '震荡',
            'target_price': None,
            'confidence': 0.7,
            'risk_score': 0.5,
            'reasoning': '基于综合分析的 T+1 研判'
        }

    def _get_default_decision(self) -> dict:
        """返回默认的 T+1 研判（不买入）"""
        return {
            'action': '关注',
            'direction': '震荡',
            'target_price': None,
            'confidence': 0.5,
            'risk_score': 0.5,
            'reasoning': '输入数据无效，默认关注（不买入）'
        }
