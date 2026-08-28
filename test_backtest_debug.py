#!/usr/bin/env python3
"""
调试回测计算
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from filter import calculate_backtest_return
from api import get_stock_history_data

def test_backtest():
    """
    测试回测计算
    """
    print("测试回测计算...")
    
    stock_code = "000001.SZ"
    print(f"测试股票: {stock_code}")
    
    # 获取历史数据
    daily_data = get_stock_history_data(stock_code, period='d', limit=200)
    
    if not daily_data:
        print("无法获取历史数据")
        return
    
    print(f"获取到 {len(daily_data)} 条数据")
    print(f"最后一条数据索引: {len(daily_data) - 1}")
    
    # 测试回测计算
    current_index = len(daily_data) - 1
    print(f"\n调用 calculate_backtest_return(data, {current_index}, 5)")
    
    result = calculate_backtest_return(daily_data, current_index, 5)
    
    print(f"\n返回结果: {result}")
    
    if result:
        print(f"5天前价格: {result['start_price']}")
        print(f"当前价格: {result['end_price']}")
        print(f"回测收益率: {result['return_rate']:.2f}%")
    else:
        print("返回None")
    
    # 手动验证
    print("\n手动验证:")
    print(f"data[{current_index - 5}]['c'] = {daily_data[current_index - 5]['c']}")
    print(f"data[{current_index}]['c'] = {daily_data[current_index]['c']}")
    
    manual_return = (daily_data[current_index]['c'] - daily_data[current_index - 5]['c']) / daily_data[current_index - 5]['c'] * 100
    print(f"手动计算收益率: {manual_return:.2f}%")

if __name__ == "__main__":
    test_backtest()
