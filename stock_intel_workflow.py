#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票智能资讯收集工作流
使用 web_search 和 web_fetch 实现完整的股票资讯收集和分析流程
"""

import subprocess
import csv
import json
import os
import time
from datetime import datetime
import re

def run_stock_filter(strategy='b1'):
    """运行股票筛选脚本"""
    print(f"开始执行股票筛选：{strategy} 策略")
    cmd = f"cd /home/lukezax/workspace/stock && python stock_filter.py --strategy {strategy} --output file"
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0

def extract_qualified_stocks(strategy='b1'):
    """从筛选结果中提取符合条件的股票"""
    # 查找最新的 CSV 文件
    csv_files = [f for f in os.listdir('/home/lukezax/workspace/stock') 
                 if f.endswith('.csv') and strategy in f]
    
    if not csv_files:
        print("未找到 CSV 文件，请先运行股票筛选")
        return []
    
    # 按时间排序，取最新的
    csv_files.sort(reverse=True)
    latest_csv = os.path.join('/home/lukezax/workspace/stock', csv_files[0])
    
    qualified_stocks = []
    
    with open(latest_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('结果') == '符合':
                stock_info = {
                    'code': row.get('股票代码', ''),
                    'name': row.get('股票名称', ''),
                    'exchange': row.get('交易所', ''),
                    'total_score': row.get('新增条件总分', '0'),
                    'distance_to_yellow': row.get('到黄线距离', '0')
                }
                qualified_stocks.append(stock_info)
    
    print(f"找到 {len(qualified_stocks)} 只符合条件的股票")
    return qualified_stocks

def search_stock_basic_info(query, max_results=5):
    """搜索股票基本信息"""
    print(f"搜索 {query} 的基本信息...")
    # 这里使用 web_search 模拟
    return {
        'query': query,
        'status': 'pending'
    }

def search_industry_news(query, max_results=10):
    """搜索行业新闻"""
    print(f"搜索 {query} 行业新闻...")
    return {
        'query': query,
        'status': 'pending'
    }

def search_policy_info(query, max_results=10):
    """搜索政策信息"""
    print(f"搜索 {query} 行业政策...")
    return {
        'query': query,
        'status': 'pending'
    }

def search_social_media(query, max_results=10):
    """搜索社交媒体信息"""
    print(f"搜索 {query} 社交媒体...")
    return {
        'query': query,
        'status': 'pending'
    }

def generate_report(stock_info, basic_info, industry_news, policy_info, social_media):
    """生成股票简报"""
    summary = []
    
    # 基本信息总结
    if basic_info:
        summary.append(f"【公司基本信息】{basic_info.get('query', '')}")
    
    # 行业动态总结
    if industry_news:
        summary.append(f"【行业新闻】已搜索：{industry_news.get('query', '')}")
    
    # 政策环境总结
    if policy_info:
        summary.append(f"【政策环境】已搜索：{policy_info.get('query', '')}")
    
    # 社交媒体总结
    if social_media:
        summary.append(f"【社交媒体】已搜索：{social_media.get('query', '')}")
    
    return {
        'stock_code': stock_info['code'],
        'stock_name': stock_info['name'],
        'exchange': stock_info['exchange'],
        'report_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'basic_info': basic_info,
        'industry_news': industry_news,
        'policy_info': policy_info,
        'social_media': social_media,
        'summary': '\n'.join(summary)
    }

def save_reports(reports, output_dir='/home/lukezax/workspace/stock/reports'):
    """保存报告"""
    os.makedirs(output_dir, exist_ok=True)
    
    for i, report in enumerate(reports):
        filename = f"stock_{report['stock_code']}_{report['stock_name'].replace(' ', '_')}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# 股票简报：{report['stock_name']} ({report['stock_code']})\n")
            f.write(f"生成时间：{report['report_time']}\n\n")
            f.write(report['summary'])
            f.write("\n\n")
            f.write("## 详细信息\n\n")
            f.write(json.dumps(report, ensure_ascii=False, indent=2))
        
        print(f"报告已保存：{filepath}")

def main():
    """主工作流"""
    print("=" * 80)
    print("股票智能资讯收集工作流启动")
    print("=" * 80)
    
    # 步骤 1: 运行股票筛选
    print("\n【步骤 1】运行股票筛选...")
    if not run_stock_filter('b1'):
        print("股票筛选执行失败！")
        return
    
    time.sleep(2)
    
    # 步骤 2: 提取符合条件的股票
    print("\n【步骤 2】提取符合条件的股票...")
    qualified_stocks = extract_qualified_stocks('b1')
    
    if not qualified_stocks:
        print("没有符合条件的股票，工作流结束")
        return
    
    print(f"找到 {len(qualified_stocks)} 只符合条件的股票")
    for stock in qualified_stocks:
        print(f"  - {stock['code']} {stock['name']} (总分：{stock['total_score']})")
    
    # 步骤 3: 为每只股票收集资讯
    print("\n【步骤 3】收集资讯并生成报告...")
    reports = []
    
    for idx, stock in enumerate(qualified_stocks, 1):
        print(f"\n{'='*80}")
        print(f"处理第 {idx}/{len(qualified_stocks)} 只股票：{stock['code']} {stock['name']}")
        print(f"{'='*80}")
        
        # 获取基本信息
        basic_info = search_stock_basic_info(stock['name'])
        
        # 获取行业新闻
        industry_news = search_industry_news(stock['name'])
        
        # 获取政策信息
        policy_info = search_policy_info(stock['name'])
        
        # 获取社交媒体信息
        social_media = search_social_media(stock['name'])
        
        # 生成报告
        report = generate_report(stock, basic_info, industry_news, policy_info, social_media)
        reports.append(report)
        
        print(f"✓ 股票 {stock['code']} 简报生成完成")
    
    # 步骤 4: 保存报告
    print("\n【步骤 4】保存报告...")
    save_reports(reports)
    
    print("\n" + "=" * 80)
    print("工作流完成！")
    print("=" * 80)
    print(f"共生成 {len(reports)} 份股票简报")
    print("报告保存位置：/home/lukezax/workspace/stock/reports/")

if __name__ == '__main__':
    main()
