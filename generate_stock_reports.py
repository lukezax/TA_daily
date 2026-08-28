#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票智能资讯收集工作流 - 使用 Tavily 搜索实现完整资讯收集

工作流步骤：
1. 执行股票筛选 (stock_filter.py)
2. 提取符合条件的股票
3. 搜索每个股票的基本信息
4. 搜索行业新闻
5. 搜索政策信息
6. 搜索社交媒体信息
7. 综合整理生成简报
"""

import subprocess
import csv
import json
import os
import time
from datetime import datetime
import sys

# Tavily 搜索 API 配置
import os
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY', '').strip()

def run_stock_filter(strategy='b1'):
    """运行股票筛选脚本"""
    print(f"\n{'='*80}")
    print(f"【步骤 1】运行股票筛选：{strategy} 策略")
    print(f"{'='*80}")
    
    cmd = f"cd /home/lukezax/workspace/stock && python stock_filter.py --strategy {strategy} --output file"
    
    print(f"执行命令：{cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3600)
    
    if result.returncode != 0:
        print(f"筛选执行失败：{result.stderr}")
        return False
    
    print("✓ 股票筛选完成")
    return True

def extract_qualified_stocks(strategy='b1'):
    """从筛选结果中提取符合条件的股票"""
    print(f"\n{'='*80}")
    print(f"【步骤 2】提取符合条件的股票")
    print(f"{'='*80}")
    
    # 查找最新的 CSV 文件
    csv_files = [f for f in os.listdir('/home/lukezax/workspace/stock') 
                 if f.endswith('.csv') and strategy in f]
    
    if not csv_files:
        print("✗ 未找到 CSV 文件，请先运行股票筛选")
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
    
    print(f"✓ 找到 {len(qualified_stocks)} 只符合条件的股票")
    for stock in qualified_stocks:
        print(f"  • {stock['code']} {stock['name']} (交易所：{stock['exchange']}, 总分：{stock['total_score']})")
    
    return qualified_stocks

def search_with_tavily(query, max_results=10):
    """使用 Tavily 进行搜索"""
    if not TAVILY_API_KEY:
        print(f"✗ Tavily API Key 未设置，跳过搜索：{query}")
        return []
    
    try:
        import requests
        
        url = "https://api.tavily.com/search"
        payload = {
            "query": query,
            "api_key": TAVILY_API_KEY,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_answer": True
        }
        
        response = requests.get(url, params=payload, timeout=30)
        if response.status_code == 200:
            return response.json().get('results', [])
        else:
            print(f"✗ Tavily 搜索失败：{response.status_code}")
            return []
    except Exception as e:
        print(f"✗ Tavily 搜索异常：{str(e)}")
        return []

def get_stock_basic_info(stock_name, code):
    """获取股票和公司基本信息"""
    print(f"\n  搜索 {stock_name} ({code}) 的基本信息...")
    
    queries = [
        f"{stock_name} 公司简介 主营业务",
        f"{stock_name} 公司 基本信息 股权结构",
        f"{stock_name} 上市公司 概况"
    ]
    
    all_results = []
    for query in queries:
        results = search_with_tavily(query, max_results=3)
        all_results.extend(results)
    
    # 去重
    seen = set()
    unique_results = []
    for r in all_results:
        key = (r.get('url', ''), r.get('title', ''))
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
    
    return {
        'queries': queries,
        'results': unique_results[:10]  # 最多 10 条
    }

def get_industry_news(stock_name):
    """搜索行业新闻"""
    print(f"  搜索 {stock_name} 行业最新动态...")
    
    queries = [
        f"{stock_name} 所属行业 新闻 2024 2025",
        f"{stock_name} 行业动态 市场趋势",
        f"{stock_name} 行业分析 最新进展"
    ]
    
    all_results = []
    for query in queries:
        results = search_with_tavily(query, max_results=5)
        all_results.extend(results)
    
    seen = set()
    unique_results = []
    for r in all_results:
        key = (r.get('url', ''), r.get('title', ''))
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
    
    return {
        'queries': queries,
        'results': unique_results[:15]
    }

def get_policy_info(stock_name):
    """搜索政策信息"""
    print(f"  搜索 {stock_name} 行业政策和形势...")
    
    queries = [
        f"{stock_name} 行业 政策 监管 2024 2025",
        f"{stock_name} 产业政策 国内外形势",
        f"{stock_name} 行业发展 政策支持"
    ]
    
    all_results = []
    for query in queries:
        results = search_with_tavily(query, max_results=5)
        all_results.extend(results)
    
    seen = set()
    unique_results = []
    for r in all_results:
        key = (r.get('url', ''), r.get('title', ''))
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
    
    return {
        'queries': queries,
        'results': unique_results[:15]
    }

def get_social_media_info(stock_name):
    """搜索社交媒体信息"""
    print(f"  搜索 {stock_name} 社交媒体信息...")
    
    queries = [
        f"{stock_name} 公司 微博 资讯",
        f"{stock_name} 公司 小红书 动态",
        f"{stock_name} 公司 抖音 话题",
        f"{stock_name} 公司 推特 Twitter"
    ]
    
    all_results = []
    for query in queries:
        results = search_with_tavily(query, max_results=3)
        all_results.extend(results)
    
    seen = set()
    unique_results = []
    for r in all_results:
        key = (r.get('url', ''), r.get('title', ''))
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
    
    return {
        'queries': queries,
        'results': unique_results[:10]
    }

def generate_summary(stock_info, basic_info, industry_news, policy_info, social_media):
    """生成综合总结"""
    summary_parts = []
    
    # 基本信息
    if basic_info:
        summary_parts.append(f"【公司基本信息】")
        for result in basic_info['results'][:3]:
            title = result.get('title', '')
            if title:
                summary_parts.append(f"  • {title}")
    
    # 行业动态
    if industry_news:
        summary_parts.append(f"\n【行业动态】")
        for result in industry_news['results'][:5]:
            title = result.get('title', '')
            if title:
                summary_parts.append(f"  • {title}")
    
    # 政策信息
    if policy_info:
        summary_parts.append(f"\n【政策环境】")
        for result in policy_info['results'][:5]:
            title = result.get('title', '')
            if title:
                summary_parts.append(f"  • {title}")
    
    # 社交媒体
    if social_media:
        summary_parts.append(f"\n【社交媒体】")
        for result in social_media['results'][:5]:
            title = result.get('title', '')
            if title:
                summary_parts.append(f"  • {title}")
    
    return '\n'.join(summary_parts)

def save_report(stock_info, basic_info, industry_news, policy_info, social_media, report_dir):
    """保存单个股票报告"""
    os.makedirs(report_dir, exist_ok=True)
    
    # 生成文件名
    safe_name = stock_info['name'].replace(' ', '_').replace('/', '_')
    filename = f"{stock_info['code']}_{safe_name}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    filepath = os.path.join(report_dir, filename)
    
    # 构建完整报告
    report_content = f"""# 股票简报：{stock_info['name']} ({stock_info['code']})

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**交易所**: {stock_info['exchange']}  
**筛选总分**: {stock_info['total_score']}  
**到黄线距离**: {stock_info['distance_to_yellow']}

---

## 综合总结

{generate_summary(stock_info, basic_info, industry_news, policy_info, social_media)}

---

## 详细信息

### 基本信息搜索
"""
    
    if basic_info:
        report_content += "#### 搜索查询\n"
        for q in basic_info['queries']:
            report_content += f"- {q}\n"
        
        report_content += "\n#### 搜索结果\n"
        for i, result in enumerate(basic_info['results'], 1):
            title = result.get('title', '')
            url = result.get('url', '')
            description = result.get('description', '')
            report_content += f"\n{i}. {title}\n"
            if url:
                report_content += f"   URL: {url}\n"
            if description:
                report_content += f"   摘要：{description}\n"
    
    report_content += f"""
### 行业动态搜索
"""
    
    if industry_news:
        report_content += "#### 搜索查询\n"
        for q in industry_news['queries']:
            report_content += f"- {q}\n"
        
        report_content += "\n#### 搜索结果\n"
        for i, result in enumerate(industry_news['results'], 1):
            title = result.get('title', '')
            url = result.get('url', '')
            description = result.get('description', '')
            report_content += f"\n{i}. {title}\n"
            if url:
                report_content += f"   URL: {url}\n"
            if description:
                report_content += f"   摘要：{description}\n"
    
    report_content += f"""
### 政策环境搜索
"""
    
    if policy_info:
        report_content += "#### 搜索查询\n"
        for q in policy_info['queries']:
            report_content += f"- {q}\n"
        
        report_content += "\n#### 搜索结果\n"
        for i, result in enumerate(policy_info['results'], 1):
            title = result.get('title', '')
            url = result.get('url', '')
            description = result.get('description', '')
            report_content += f"\n{i}. {title}\n"
            if url:
                report_content += f"   URL: {url}\n"
            if description:
                report_content += f"   摘要：{description}\n"
    
    report_content += f"""
### 社交媒体搜索
"""
    
    if social_media:
        report_content += "#### 搜索查询\n"
        for q in social_media['queries']:
            report_content += f"- {q}\n"
        
        report_content += "\n#### 搜索结果\n"
        for i, result in enumerate(social_media['results'], 1):
            title = result.get('title', '')
            url = result.get('url', '')
            description = result.get('description', '')
            report_content += f"\n{i}. {title}\n"
            if url:
                report_content += f"   URL: {url}\n"
            if description:
                report_content += f"   摘要：{description}\n"
    
    report_content += f"""
---
**免责声明**: 本报告仅供参考，不构成投资建议。
"""
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    print(f"✓ 报告已保存：{filepath}")
    return filepath

def main():
    """主工作流"""
    print("\n" + "="*80)
    print("股票智能资讯收集工作流")
    print("="*80)
    print(f"启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查 Tavily API Key
    tavily_key = os.environ.get('TAVILY_API_KEY', '')
    if tavily_key:
        print(f"✓ Tavily API Key 已设置")
    else:
        print(f"⚠ Tavily API Key 未设置，搜索功能将不可用")
        print(f"  设置方法：export TAVILY_API_KEY='your-api-key'")
    
    print("="*80)
    
    # 步骤 1: 运行股票筛选
    if not run_stock_filter('b1'):
        print("\n✗ 工作流终止：股票筛选失败")
        return
    
    time.sleep(2)
    
    # 步骤 2: 提取符合条件的股票
    qualified_stocks = extract_qualified_stocks('b1')
    
    if not qualified_stocks:
        print("\n✗ 工作流终止：没有符合条件的股票")
        return
    
    print(f"\n{'='*80}")
    print(f"【步骤 3】开始资讯收集")
    print(f"{'='*80}")
    
    # 创建报告目录
    report_dir = '/home/lukezax/workspace/stock/reports'
    
    # 步骤 3: 为每只股票收集资讯并生成报告
    reports = []
    
    for idx, stock in enumerate(qualified_stocks, 1):
        print(f"\n{'='*80}")
        print(f"处理第 {idx}/{len(qualified_stocks)} 只股票")
        print(f"{'='*80}")
        print(f"股票代码：{stock['code']}")
        print(f"股票名称：{stock['name']}")
        print(f"交易所：{stock['exchange']}")
        
        # 获取各类信息
        basic_info = get_stock_basic_info(stock['name'], stock['code'])
        industry_news = get_industry_news(stock['name'])
        policy_info = get_policy_info(stock['name'])
        social_media = get_social_media_info(stock['name'])
        
        # 保存报告
        save_report(stock, basic_info, industry_news, policy_info, social_media, report_dir)
        
        reports.append({
            'stock': stock,
            'basic_info': basic_info,
            'industry_news': industry_news,
            'policy_info': policy_info,
            'social_media': social_media
        })
        
        print(f"✓ 股票 {stock['code']} 简报生成完成")
        
        # 短暂延迟，避免 API 限流
        if idx < len(qualified_stocks):
            time.sleep(1)
    
    # 步骤 4: 生成汇总报告
    print(f"\n{'='*80}")
    print(f"【步骤 4】生成汇总报告")
    print(f"{'='*80}")
    
    summary_file = os.path.join(report_dir, 'summary_report.md')
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("# 股票资讯收集汇总报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## 统计\n\n")
        f.write(f"- 符合条件的股票数量：{len(qualified_stocks)}\n")
        f.write(f"- 报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## 股票列表\n\n")
        f.write("| 股票代码 | 股票名称 | 交易所 | 总分 | 到黄线距离 |\n")
        f.write("|----------|----------|--------|------|------------|\n")
        
        for stock in qualified_stocks:
            f.write(f"| {stock['code']} | {stock['name']} | {stock['exchange']} | {stock['total_score']} | {stock['distance_to_yellow']} |\n")
        
        f.write(f"\n## 报告文件\n\n")
        for i, report in enumerate(reports, 1):
            stock = report['stock']
            safe_name = stock['name'].replace(' ', '_').replace('/', '_')
            filename = f"{stock['code']}_{safe_name}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            f.write(f"- {i}. [{stock['code']}] {stock['name']} - [查看报告]({filename})\n")
    
    print(f"✓ 汇总报告已保存：{summary_file}")
    
    print("\n" + "="*80)
    print("工作流完成！")
    print("="*80)
    print(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"共处理：{len(qualified_stocks)} 只股票")
    print(f"报告目录：{report_dir}")
    print("="*80 + "\n")

if __name__ == '__main__':
    main()
