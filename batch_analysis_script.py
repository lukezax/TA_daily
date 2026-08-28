#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量股票分析脚本
基于 stock 项目的筛选结果，使用 TradingAgents-CN 进行批量分析
"""

import csv
import os
import sys
from pathlib import Path
from datetime import datetime
import json

# 添加 TradingAgents-CN 到路径
TRADING_AGENTS_PATH = "/home/lukezax/workspace/TradingAgents-CN"
sys.path.insert(0, TRADING_AGENTS_PATH)

# 配置文件路径
CSV_FILE = "/home/lukezax/workspace/stock/b1_filtered_stocks_20260402_021729.csv"
OUTPUT_DIR = "/home/lukezax/workspace/stock/analysis_reports"
REPORT_FILE = os.path.join(OUTPUT_DIR, "batch_analysis_report_{}.md".format(datetime.now().strftime("%Y%m%d_%H%M%S")))

def read_filtered_stocks(csv_path):
    """读取筛选结果文件，提取符合的股票"""
    stocks = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('结果') == '符合' and row.get('状态') == '成功':
                stocks.append({
                    'code': row['股票代码'],
                    'name': row['股票名称'],
                    'exchange': row['交易所'],
                    'close_price': float(row['收盘价']),
                    'volume': float(row['volume']),
                    'total_market_cap': float(row['总市值']),
                    'message': row.get('message', '处理成功')
                })
    return stocks

def generate_analysis_plan(stocks):
    """生成分析计划"""
    plan = {
        'total_stocks': len(stocks),
        'stocks': stocks,
        'analysis_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'status': 'pending'
    }
    return plan

def save_analysis_plan(plan, output_path):
    """保存分析计划"""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"✓ 分析计划已保存：{output_path}")

def main():
    print("=" * 60)
    print("批量股票分析脚本")
    print("=" * 60)
    
    # 1. 读取筛选结果
    print(f"\n[1/4] 读取筛选结果：{CSV_FILE}")
    if not os.path.exists(CSV_FILE):
        print(f"❌ 文件不存在：{CSV_FILE}")
        sys.exit(1)
    
    stocks = read_filtered_stocks(CSV_FILE)
    print(f"✓ 找到 {len(stocks)} 只符合条件的股票")
    
    # 显示前 10 只股票
    print("\n符合条件的股票列表:")
    print("-" * 60)
    for i, stock in enumerate(stocks[:10], 1):
        print(f"{i:2}. {stock['code']} {stock['name']} ({stock['exchange']}) - 现价：{stock['close_price']:.2f}")
    if len(stocks) > 10:
        print(f"... 还有 {len(stocks) - 10} 只股票")
    
    # 2. 创建输出目录
    print(f"\n[2/4] 准备输出目录：{OUTPUT_DIR}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("✓ 输出目录已就绪")
    
    # 3. 生成分析计划
    print(f"\n[3/4] 生成分析计划")
    plan = generate_analysis_plan(stocks)
    plan_path = os.path.join(OUTPUT_DIR, "analysis_plan.json")
    save_analysis_plan(plan, plan_path)
    
    # 4. 生成报告
    print(f"\n[4/4] 生成分析报告：{REPORT_FILE}")
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write("# 批量股票分析报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**股票数量**: {len(stocks)}\n")
        f.write(f"**数据来源**: {CSV_FILE}\n\n")
        
        f.write("## 筛选条件\n")
        f.write("- 原始筛选：B1 策略\n")
        f.write("- 过滤条件：符合所有技术指标和基本面条件\n")
        f.write("- 数据来源：stock 项目\n\n")
        
        f.write("## 符合条件的股票列表\n\n")
        f.write("| 序号 | 股票代码 | 股票名称 | 交易所 | 现价 | 总市值 |\n")
        f.write("|------|----------|----------|--------|------|--------|\n")
        
        for i, stock in enumerate(stocks, 1):
            f.write(f"| {i} | {stock['code']} | {stock['name']} | {stock['exchange']} | {stock['close_price']:.2f} | {stock['total_market_cap']/1e8:.2f}亿 |\n")
        
        f.write("\n## 分析说明\n\n")
        f.write("本分析报告基于 TradingAgents-CN 多智能体分析框架。\n\n")
        f.write("### 分析流程\n")
        f.write("1. 使用 stock 项目的 B1 策略进行初步筛选\n")
        f.write("2. 应用多重技术指标过滤（K 线、MACD、成交量等）\n")
        f.write("3. 基本面数据分析（PE、PB、ROE 等）\n")
        f.write("4. 风险控制检查（连续涨停、换手率异常等）\n")
        f.write("5. TradingAgents-CN 多智能体深度分析\n\n")
        
        f.write("### 下一步操作\n")
        f.write("1. 运行批量分析脚本进行完整分析\n")
        f.write("2. 查看分析结果和详细报告\n")
        f.write("3. 根据分析结果制定投资策略\n\n")
        
        f.write("## 风险提示\n")
        f.write("⚠️ 本分析结果仅供参考，不构成投资建议。\n")
        f.write("投资有风险，入市需谨慎。\n")
    
    print("✓ 分析报告已生成")
    
    # 总结
    print("\n" + "=" * 60)
    print("✓ 准备工作完成！")
    print("=" * 60)
    print(f"\n输出文件:")
    print(f"  - 分析报告：{REPORT_FILE}")
    print(f"  - 分析计划：{plan_path}")
    print(f"  - 输出目录：{OUTPUT_DIR}")
    print(f"\n共 {len(stocks)} 只股票等待分析")

if __name__ == "__main__":
    main()
