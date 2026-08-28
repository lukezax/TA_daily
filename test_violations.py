#!/usr/bin/env python3
"""
测试违规次数计算是否正确
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from filter import b1_strategy_filter
from api import get_stock_history_data

def test_violations():
    """
    测试违规次数计算
    """
    print("测试违规次数计算...")
    
    # 使用一个真实股票测试
    stock_code = "000001.SZ"
    
    print(f"测试股票: {stock_code}")
    
    # 获取历史数据
    print("获取历史数据...")
    daily_data = get_stock_history_data(stock_code, period='d', limit=200)
    weekly_data = get_stock_history_data(stock_code, period='w', limit=100)
    
    if not daily_data:
        print("无法获取历史数据，测试失败")
        return
    
    print(f"获取到 {len(daily_data)} 条日线数据")
    
    # 执行筛选
    print("执行B1策略筛选...")
    result = b1_strategy_filter(daily_data, weekly_data)
    
    if not result:
        print("筛选失败或数据不足")
        return
    
    # 输出违规次数
    print("\n=== 违规次数统计 ===")
    indicators = result.get('indicators', {})
    
    print(f"30日连续2日涨幅违规次数: {indicators.get('30日连续2日涨幅违规次数', 0)}")
    print(f"30日连续3日涨幅违规次数: {indicators.get('30日连续3日涨幅违规次数', 0)}")
    print(f"30日单日换手率违规次数: {indicators.get('30日单日换手率违规次数', 0)}")
    print(f"30日单周换手率违规次数: {indicators.get('30日单周换手率违规次数', 0)}")
    print(f"120日大量卖出次数: {indicators.get('120日大量卖出次数', 0)}")
    
    # 手动检查最近30天的涨幅
    print("\n=== 手动验证最近30天涨幅 ===")
    close_prices = [item['c'] for item in daily_data]
    
    if len(close_prices) >= 30:
        print("检查最近30天的连续2日涨幅...")
        violations_2day = 0
        for i in range(len(close_prices) - 30, len(close_prices)):
            if i >= 2 and close_prices[i-2] > 0:
                rate_2day = (close_prices[i] / close_prices[i-2] - 1) * 100
                if rate_2day > 40:
                    violations_2day += 1
                    print(f"  第{i}天: 2日涨幅 {rate_2day:.2f}% (超过40%)")
        
        if violations_2day == 0:
            print("  没有发现2日涨幅超过40%的情况")
        
        print("\n检查最近30天的连续3日涨幅...")
        violations_3day = 0
        for i in range(len(close_prices) - 30, len(close_prices)):
            if i >= 3 and close_prices[i-3] > 0:
                rate_3day = (close_prices[i] / close_prices[i-3] - 1) * 100
                if rate_3day > 50:
                    violations_3day += 1
                    print(f"  第{i}天: 3日涨幅 {rate_3day:.2f}% (超过50%)")
        
        if violations_3day == 0:
            print("  没有发现3日涨幅超过50%的情况")
    
    # 检查5天回测
    print("\n=== 5天回测数据 ===")
    print(f"5天前价格: {indicators.get('5天前价格', 0)}")
    print(f"5天回测收益率: {indicators.get('5天回测收益率', 0):.2f}%")
    
    # 手动验证
    if len(close_prices) >= 6:
        price_5days_ago = close_prices[-6]
        current_price = close_prices[-1]
        manual_return = (current_price - price_5days_ago) / price_5days_ago * 100
        print(f"\n手动计算验证:")
        print(f"  5天前价格: {price_5days_ago:.2f}")
        print(f"  当前价格: {current_price:.2f}")
        print(f"  5天回测收益率: {manual_return:.2f}%")
    
    print("\n测试完成！")

if __name__ == "__main__":
    test_violations()
