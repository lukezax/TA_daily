"""
模拟数据模块
用于测试，避免频繁调用API
"""

def get_mock_stock_list():
    """
    获取模拟股票列表
    """
    return [
        {'code': '000001.SZ', 'name': '平安银行', 'exchange': 'SZ'},
        {'code': '000002.SZ', 'name': '万 科 A', 'exchange': 'SZ'},
        {'code': '000006.SZ', 'name': '深振业 A', 'exchange': 'SZ'},
        {'code': '000007.SZ', 'name': '全新好', 'exchange': 'SZ'},
        {'code': '000008.SZ', 'name': '神州高铁', 'exchange': 'SZ'},
        {'code': '000009.SZ', 'name': '中国宝安', 'exchange': 'SZ'},
        {'code': '000010.SZ', 'name': '美丽生态', 'exchange': 'SZ'},
        {'code': '000011.SZ', 'name': '深物业 A', 'exchange': 'SZ'},
        {'code': '000012.SZ', 'name': '南 玻 A', 'exchange': 'SZ'},
        {'code': '000014.SZ', 'name': '沙河股份', 'exchange': 'SZ'},
    ]

def get_mock_stock_history_data(stock_code, period='d', limit=200):
    """
    获取模拟股票历史数据
    """
    from api import get_stock_history_data
    # 实际还是调用真实 API
    return get_stock_history_data(stock_code, period=period, limit=limit)
