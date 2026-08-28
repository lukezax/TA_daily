"""
股票工具函数
提供股票代码识别、分类和处理功能
"""

import re
from typing import Dict, Tuple, Optional
from enum import Enum

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


class StockMarket(Enum):
    """股票市场枚举"""
    CHINA_A = "china_a"      # 中国A股
    HONG_KONG = "hong_kong"  # 港股
    US = "us"                # 美股
    UNKNOWN = "unknown"      # 未知


class StockUtils:
    """股票工具类"""
    
    @staticmethod
    def identify_stock_market(ticker: str) -> StockMarket:
        """
        识别股票代码所属市场

        Args:
            ticker: 股票代码

        Returns:
            StockMarket: 股票市场类型
        """
        if not ticker:
            return StockMarket.UNKNOWN

        ticker = str(ticker).strip().upper()

        # 中国A股：6位数字
        if re.match(r'^\d{6}$', ticker):
            return StockMarket.CHINA_A

        # 港股：4-5位数字.HK 或 纯4-5位数字（支持0700.HK、09988.HK、00700、9988格式）
        if re.match(r'^\d{4,5}\.HK$', ticker) or re.match(r'^\d{4,5}$', ticker):
            return StockMarket.HONG_KONG

        # 美股：1-5位字母
        if re.match(r'^[A-Z]{1,5}$', ticker):
            return StockMarket.US

        return StockMarket.UNKNOWN
    
    @staticmethod
    def is_china_stock(ticker: str) -> bool:
        """
        判断是否为中国A股
        
        Args:
            ticker: 股票代码
            
        Returns:
            bool: 是否为中国A股
        """
        return StockUtils.identify_stock_market(ticker) == StockMarket.CHINA_A
    
    @staticmethod
    def is_hk_stock(ticker: str) -> bool:
        """
        判断是否为港股
        
        Args:
            ticker: 股票代码
            
        Returns:
            bool: 是否为港股
        """
        return StockUtils.identify_stock_market(ticker) == StockMarket.HONG_KONG
    
    @staticmethod
    def is_us_stock(ticker: str) -> bool:
        """
        判断是否为美股
        
        Args:
            ticker: 股票代码
            
        Returns:
            bool: 是否为美股
        """
        return StockUtils.identify_stock_market(ticker) == StockMarket.US
    
    @staticmethod
    def get_currency_info(ticker: str) -> Tuple[str, str]:
        """
        根据股票代码获取货币信息
        
        Args:
            ticker: 股票代码
            
        Returns:
            Tuple[str, str]: (货币名称, 货币符号)
        """
        market = StockUtils.identify_stock_market(ticker)
        
        if market == StockMarket.CHINA_A:
            return "人民币", "¥"
        elif market == StockMarket.HONG_KONG:
            return "港币", "HK$"
        elif market == StockMarket.US:
            return "美元", "$"
        else:
            return "未知", "?"
    
    @staticmethod
    def get_data_source(ticker: str) -> str:
        """
        根据股票代码获取推荐的数据源
        
        Args:
            ticker: 股票代码
            
        Returns:
            str: 数据源名称
        """
        market = StockUtils.identify_stock_market(ticker)
        
        if market == StockMarket.CHINA_A:
            return "china_unified"  # 使用统一的中国股票数据源
        elif market == StockMarket.HONG_KONG:
            return "yahoo_finance"  # 港股使用Yahoo Finance
        elif market == StockMarket.US:
            return "yahoo_finance"  # 美股使用Yahoo Finance
        else:
            return "unknown"
    
    @staticmethod
    def normalize_hk_ticker(ticker: str) -> str:
        """
        标准化港股代码格式
        
        Args:
            ticker: 原始港股代码
            
        Returns:
            str: 标准化后的港股代码
        """
        if not ticker:
            return ticker
            
        ticker = str(ticker).strip().upper()
        
        # 如果是纯4-5位数字，添加.HK后缀
        if re.match(r'^\d{4,5}$', ticker):
            return f"{ticker}.HK"

        # 如果已经是正确格式，直接返回
        if re.match(r'^\d{4,5}\.HK$', ticker):
            return ticker
            
        return ticker
    
    @staticmethod
    def get_market_info(ticker: str) -> Dict:
        """
        获取股票市场的详细信息
        
        Args:
            ticker: 股票代码
            
        Returns:
            Dict: 市场信息字典
        """
        market = StockUtils.identify_stock_market(ticker)
        currency_name, currency_symbol = StockUtils.get_currency_info(ticker)
        data_source = StockUtils.get_data_source(ticker)
        
        market_names = {
            StockMarket.CHINA_A: "中国A股",
            StockMarket.HONG_KONG: "港股",
            StockMarket.US: "美股",
            StockMarket.UNKNOWN: "未知市场"
        }
        
        return {
            "ticker": ticker,
            "market": market.value,
            "market_name": market_names[market],
            "currency_name": currency_name,
            "currency_symbol": currency_symbol,
            "data_source": data_source,
            "is_china": market == StockMarket.CHINA_A,
            "is_hk": market == StockMarket.HONG_KONG,
            "is_us": market == StockMarket.US
        }


# 便捷函数，保持向后兼容
def is_china_stock(ticker: str) -> bool:
    """判断是否为中国A股（向后兼容）"""
    return StockUtils.is_china_stock(ticker)


def is_hk_stock(ticker: str) -> bool:
    """判断是否为港股"""
    return StockUtils.is_hk_stock(ticker)


def is_us_stock(ticker: str) -> bool:
    """判断是否为美股"""
    return StockUtils.is_us_stock(ticker)


def get_stock_market_info(ticker: str) -> Dict:
    """获取股票市场信息"""
    return StockUtils.get_market_info(ticker)


# ==================== 价格提取工具 ====================

# 增强正则模式：覆盖 LLM 可能输出的多种价格格式
PRICE_PATTERNS = [
    r'当前价格[：:]\s*[¥￥]?([\d.]+)',
    r'\*\*当前价格\*\*[：:]\s*[¥￥]?([\d.]+)',
    r'最新价格[：:]\s*[¥￥]?([\d.]+)',
    r'💰\s*最新价格[：:]\s*[¥￥]?([\d.]+)',
    r'收盘价[：:]\s*[¥￥]?([\d.]+)',
    r'现价[：:]\s*[¥￥]?([\d.]+)',
    r'股价[：:]\s*[¥￥]?([\d.]+)',
    r'价格[：:]\s*[¥￥]([\d.]+)',
]


def extract_price_from_report(report_text: str) -> Optional[str]:
    """
    从市场分析报告中提取股票价格（增强正则匹配多种格式）

    Args:
        report_text: 市场分析报告文本

    Returns:
        提取到的价格字符串，如 "40.50"；未匹配到返回 None
    """
    if not report_text:
        return None
    for pattern in PRICE_PATTERNS:
        match = re.search(pattern, report_text)
        if match:
            return match.group(1)
    return None


def get_realtime_price(ticker: str) -> Optional[str]:
    """
    从数据源直接获取实时价格（智兔 API → MongoDB market_quotes）

    Args:
        ticker: 股票代码（6位数字）

    Returns:
        价格字符串如 "40.50"；获取失败返回 None
    """
    import os, sys

    # 1. 尝试智兔 API
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        app_path = os.path.join(project_root, 'app')
        if app_path not in sys.path:
            sys.path.insert(0, app_path)
        from app.services.data_sources.zhitu_adapter import ZhituAdapter
        zhitu = ZhituAdapter()
        if zhitu.is_available():
            quote = zhitu.get_single_realtime_quote(ticker)
            if quote and quote.get("close"):
                price = f"{quote['close']:.2f}"
                logger.info(f"✅ [价格获取] 智兔API: {ticker} = ¥{price}")
                return price
    except Exception as e:
        logger.debug(f"⚠️ [价格获取] 智兔API失败: {e}")

    # 2. 尝试 MongoDB market_quotes
    try:
        from tradingagents.config.database_manager import get_database_manager
        db_manager = get_database_manager()
        if db_manager.is_mongodb_available():
            client = db_manager.get_mongodb_client()
            db = client['tradingagents']
            code6 = ticker.replace('.SH', '').replace('.SZ', '').zfill(6)
            quote = db.market_quotes.find_one({"code": code6})
            if quote and quote.get("close"):
                price = f"{float(quote['close']):.2f}"
                logger.info(f"✅ [价格获取] MongoDB: {ticker} = ¥{price}")
                return price
    except Exception as e:
        logger.debug(f"⚠️ [价格获取] MongoDB失败: {e}")

    return None


def extract_price_with_fallback(ticker: str, report_text: str) -> str:
    """
    从报告中提取价格，失败则从数据源直接获取

    Args:
        ticker: 股票代码
        report_text: 市场分析报告文本

    Returns:
        价格字符串，如 "40.50"；所有方式都失败返回 "未知"
    """
    # 先从报告正则提取
    price = extract_price_from_report(report_text)
    if price:
        return price

    # 正则失败，从数据源获取
    logger.warning(f"⚠️ [价格提取] 正则匹配失败，尝试数据源直接获取: {ticker}")
    price = get_realtime_price(ticker)
    if price:
        return price

    logger.error(f"❌ [价格提取] 所有方式均失败: {ticker}")
    return "未知"
