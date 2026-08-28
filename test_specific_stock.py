#!/usr/bin/env python3
"""
测试特定股票
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from filter import b1_strategy_filter
from api import get_stock_history_data

def test_stock(stock_code):
    """
    测试特定股票
    """
    print(f"测试股票: {stock_code}")
    
    # 获取历史数据
    daily_data = get_stock_history_data(stock_code, period='d', limit=200)
    weekly_data = get_stock_history_data(stock_code, period='w', limit=100)
    
    if not daily_data:
        print("无法获取日线数据")
        return
    
    print(f"获取到 {len(daily_data)} 条日线数据")
    
    if weekly_data:
        print(f"获取到 {len(weekly_data)} 条周线数据")
    else:
        print("无周线数据")
    
    # 执行筛选
    print("\n执行B1策略筛选...")
    result = b1_strategy_filter(daily_data, weekly_data)
    
    print(f"\n返回结果类型: {type(result)}")
    print(f"返回结果: {result}")
    
    if isinstance(result, dict):
        print("\n返回了字典，包含以下键:")
        for key in result.keys():
            print(f"  - {key}")
    elif result == False:
        print("\n返回了False，说明数据不足或不满足基本条件")

if __name__ == "__main__":
    test_stock("001280.SZ")
