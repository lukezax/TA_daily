#!/usr/bin/env python3
"""
使用模拟数据测试B1策略，确保有符合条件的股票
"""

import sys
import os
import random
import datetime

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def create_mock_b1_compliant_data():
    """
    创建符合B1条件的模拟数据
    """
    data = []
    base_price = 10.0
    base_volume = 100000
    
    # 生成150天的数据
    for i in range(150):
        # 模拟价格在9-11之间波动
        price_change = random.uniform(-0.05, 0.05)
        base_price = max(8.0, min(12.0, base_price * (1 + price_change)))
        
        # 模拟成交量
        volume = base_volume * random.uniform(0.5, 2.0)
        
        # 在第30天和第60天制造倍量
        if i == 30 or i == 60:
            volume = base_volume * 2.5
        
        # 最后几天的数据要符合B1条件
        if i >= 140:
            # J值要小于13，通过调整价格实现
            if i == 149:  # 最后一天
                base_price = 10.5  # 确保收盘价合适
                volume = base_volume * 0.8  # 避免大量卖出
        
        data.append({
            't': (datetime.datetime.now() - datetime.timedelta(days=150-i)).strftime('%Y-%m-%d %H:%M:%S'),
            'o': round(base_price * random.uniform(0.99, 1.01), 2),
            'h': round(base_price * random.uniform(1.00, 1.02), 2),
            'l': round(base_price * random.uniform(0.98, 1.00), 2),
            'c': round(base_price, 2),
            'v': int(volume),
            'a': int(volume * base_price),
            'pc': round(base_price * 0.99, 2),
            'sf': 0.0
        })
    
    return data

def test_with_compliant_data():
    """
    使用符合条件的模拟数据测试
    """
    print("创建符合B1条件的模拟数据...")
    
    from filter import b1_strategy_filter
    
    # 创建日线数据
    daily_data = create_mock_b1_compliant_data()
    
    # 创建简单的周线数据
    weekly_data = []
    for i in range(0, len(daily_data), 5):
        week_data = daily_data[i:i+5]
        if week_data:
            weekly_data.append({
                't': week_data[-1]['t'],
                'o': week_data[0]['o'],
                'h': max(d['h'] for d in week_data),
                'l': min(d['l'] for d in week_data),
                'c': week_data[-1]['c'],
                'v': sum(d['v'] for d in week_data),
                'a': sum(d['a'] for d in week_data),
                'pc': week_data[0]['pc'],
                'sf': 0.0
            })
    
    print(f"生成了 {len(daily_data)} 条日线数据和 {len(weekly_data)} 条周线数据")
    
    # 执行筛选
    print("执行B1策略筛选...")
    result = b1_strategy_filter(daily_data, weekly_data)
    
    if not result:
        print("筛选失败或数据不足")
        return
    
    # 输出结果
    print("\n=== 筛选结果 ===")
    print(f"原始B1条件满足: {result.get('original_b1_result', False)}")
    print(f"所有条件满足: {result.get('all_conditions_result', False)}")
    print(f"新增条件总分: {result.get('new_conditions_score', 0)}/4")
    
    print("\n=== 原始B1条件详情 ===")
    conditions = result.get('conditions', {})
    original_b1_conditions = [
        'J<13', '收盘价>MA60', '收盘价>ZXDKX', 'ZXDQ>ZXDKX', '振幅<7', 
        '涨幅>=-2', '涨幅<2', '倍量柱条件', '市值条件', 
        'n-1日K在黄白值之间', 'n-1周K高于白线'
    ]
    
    for condition in original_b1_conditions:
        if condition in conditions:
            satisfied = conditions[condition]
            status = "✓" if satisfied else "✗"
            print(f"{status} {condition}")
    
    print("\n=== 新增条件详情 ===")
    new_conditions = [
        '30日内倍量条件', '120日内无大量卖出', 
        '30日内涨幅控制', '30日内换手率控制'
    ]
    
    for condition in new_conditions:
        if condition in conditions:
            satisfied = conditions[condition]
            status = "✓" if satisfied else "✗"
            print(f"{status} {condition}")
    
    print("\n=== 各新增条件单独显示 ===")
    indicators = result.get('indicators', {})
    individual_conditions = [
        '新增条件1_30日内倍量', '新增条件2_120日内无大量卖出',
        '新增条件3_30日内涨幅控制', '新增条件4_30日内换手率控制'
    ]
    
    for condition in individual_conditions:
        if condition in indicators:
            satisfied = indicators[condition]
            status = "✓" if satisfied else "✗"
            print(f"{status} {condition}")
    
    print("\n=== 关键指标 ===")
    key_indicators = [
        '收盘价', '白线', '黄线', 'J', '振幅', '涨幅',
        '30日倍量次数', '120日最大成交量', '120日大量卖出次数'
    ]
    
    for indicator in key_indicators:
        if indicator in indicators:
            value = indicators[indicator]
            if isinstance(value, float):
                print(f"{indicator}: {value:.2f}")
            else:
                print(f"{indicator}: {value}")
    
    print("\n测试完成！")

if __name__ == "__main__":
    test_with_compliant_data()