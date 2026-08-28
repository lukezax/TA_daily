#!/usr/bin/env python3
"""
测试增强版B1策略的脚本
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from filter import b1_strategy_filter
from api import get_stock_history_data
from mock_data import get_mock_stock_list

def test_enhanced_b1():
    """
    测试增强版B1策略
    """
    print("开始测试增强版B1策略...")
    
    # 获取测试股票列表
    stock_list = get_mock_stock_list()
    test_stock = stock_list[0]  # 使用第一只股票进行测试
    
    print(f"测试股票: {test_stock['code']} - {test_stock['name']}")
    
    # 获取历史数据
    print("获取历史数据...")
    daily_data = get_stock_history_data(test_stock['code'], period='d', limit=200)
    weekly_data = get_stock_history_data(test_stock['code'], period='w', limit=100)
    
    if not daily_data:
        print("无法获取历史数据，测试失败")
        return
    
    print(f"获取到 {len(daily_data)} 条日线数据")
    if weekly_data:
        print(f"获取到 {len(weekly_data)} 条周线数据")
    
    # 执行筛选
    print("执行B1策略筛选...")
    result = b1_strategy_filter(daily_data, weekly_data)
    
    if not result:
        print("筛选失败或数据不足")
        return
    
    # 输出结果
    print("\n=== 筛选结果 ===")
    print(f"所有条件满足: {result.get('result', False)}")
    print(f"原始B1条件满足: {result.get('original_b1_result', False)}")
    print(f"新增条件总分: {result.get('new_conditions_score', 0)}/4")
    
    print("\n=== 条件详情 ===")
    conditions = result.get('conditions', {})
    for condition, satisfied in conditions.items():
        status = "✓" if satisfied else "✗"
        print(f"{status} {condition}")
    
    print("\n=== 关键指标 ===")
    indicators = result.get('indicators', {})
    key_indicators = [
        '收盘价', '白线', '黄线', 'J', '振幅', '涨幅',
        '30日倍量次数', '120日最大成交量', '120日大量卖出次数',
        '30日连续2日涨幅违规次数', '30日连续3日涨幅违规次数'
    ]
    
    for indicator in key_indicators:
        if indicator in indicators:
            value = indicators[indicator]
            if isinstance(value, float):
                print(f"{indicator}: {value:.2f}")
            else:
                print(f"{indicator}: {value}")
    
    print("\n=== 新增条件详细分析 ===")
    # 新增条件现在单独返回
    new_conditions_results = [
        ('新增条件1_30日内倍量', result.get('new_condition_1', False)),
        ('新增条件2_120日内无大量卖出', result.get('new_condition_2', False)),
        ('新增条件3_30日内涨幅控制', result.get('new_condition_3', False)),
        ('新增条件4_30日内换手率控制', result.get('new_condition_4', False))
    ]
    
    for condition_name, satisfied in new_conditions_results:
        status = "✓ 满足" if satisfied else "✗ 不满足"
        print(f"{condition_name}: {status}")
    
    # 如果满足B1+新条件，显示回测信息
    if result.get('original_b1_result', False) and result.get('new_conditions_score', 0) > 0:
        print(f"\n=== 回测信息 ===")
        print("该股票满足B1基础条件且新增条件得分 > 0，符合回测条件")
        if '5天回测收益率' in indicators:
            print(f"5天回测收益率: {indicators['5天回测收益率']:.2f}%")
            print(f"5天后价格: {indicators.get('5天后价格', 0):.2f}")
        else:
            print("回测数据暂未计算")
    
    print("\n测试完成！")

if __name__ == "__main__":
    test_enhanced_b1()