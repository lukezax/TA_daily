#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票智能资讯收集工作流 - 使用 OpenClaw web_search 工具实现
"""

import subprocess
import csv
import json
import os
import time
from datetime import datetime

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
    
    csv_files = [f for f in os.listdir('/home/lukezax/workspace/stock') 
                 if f.endswith('.csv') and strategy in f]
    
    if not csv_files:
        print("✗ 未找到 CSV 文件，请先运行股票筛选")
        return []
    
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
    for stock in qualified_stocks[:5]:  # 只显示前 5 个
        print(f"  • {stock['code']} {stock['name']} (交易所：{stock['exchange']}, 总分：{stock['total_score']})")
    if len(qualified_stocks) > 5:
        print(f"  ... 还有 {len(qualified_stocks) - 5} 只股票")
    
    return qualified_stocks

def generate_report(stock_info):
    """生成股票简报（使用 web_search 工具）"""
    print(f"\n  正在搜索 {stock_info['name']} 的资讯...")
    
    report = {
        'stock_code': stock_info['code'],
        'stock_name': stock_info['name'],
        'exchange': stock_info['exchange'],
        'report_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_score': stock_info['total_score'],
        'distance_to_yellow': stock_info['distance_to_yellow']
    }
    
    return report

def save_report(report, report_dir):
    """保存单个股票报告"""
    os.makedirs(report_dir, exist_ok=True)
    
    safe_name = report['stock_name'].replace(' ', '_').replace('/', '_')
    filename = f"{report['stock_code']}_{safe_name}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    filepath = os.path.join(report_dir, filename)
    
    report_content = f"""# 股票简报：{report['stock_name']} ({report['stock_code']})

**生成时间**: {report['report_time']}  
**交易所**: {report['exchange']}  
**筛选总分**: {report['total_score']}  
**到黄线距离**: {report['distance_to_yellow']}

---

## 待搜索信息

> ⚠️ **说明**: 本报告已生成框架，但搜索数据需要使用 OpenClaw web_search 工具。
> 
> 请运行以下命令获取实际搜索数据：
> ```bash
> python -c "
> import subprocess
> stock_name = '{report['stock_name']}'
> stock_code = '{report['stock_code']}'
> 
> print('### 公司基本信息')
> results = subprocess.run(['openclaw', 'web_search', '-q', f'{stock_name} 公司简介 主营业务'], capture_output=True, text=True)
> print(results.stdout)
> 
> print('### 行业动态')
> results = subprocess.run(['openclaw', 'web_search', '-q', f'{stock_name} 行业 新闻 动态'], capture_output=True, text=True)
> print(results.stdout)
> 
> print('### 政策信息')
> results = subprocess.run(['openclaw', 'web_search', '-q', f'{stock_name} 行业 政策 形势'], capture_output=True, text=True)
> print(results.stdout)
> ```

---

## 信息收集清单

### 1. 公司基本信息
- [ ] 公司简介与主营业务
- [ ] 股权结构与实际控制人
- [ ] 财务数据概览
- [ ] 行业分类与竞争地位

### 2. 行业动态
- [ ] 行业最新新闻
- [ ] 市场趋势分析
- [ ] 竞争对手动态
- [ ] 技术面/基本面热点

### 3. 政策法规
- [ ] 国家产业政策解读
- [ ] 行业监管政策变化
- [ ] 国际形势影响分析
- [ ] 资本市场相关政策

### 4. 社交媒体
- [ ] 微博相关资讯
- [ ] 小红书动态
- [ ] 抖音话题
- [ ] 推特 (Twitter) 信息

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
    print("股票智能资讯收集工作流（web_search 版）")
    print("="*80)
    print(f"启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("注：使用 OpenClaw web_search 工具进行资讯收集")
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
    print(f"【步骤 3】开始生成报告模板")
    print(f"{'='*80}")
    
    # 创建报告目录
    report_dir = '/home/lukezax/workspace/stock/reports'
    
    # 步骤 3: 为每只股票生成报告模板
    reports = []
    
    for idx, stock in enumerate(qualified_stocks, 1):
        print(f"\n{'='*80}")
        print(f"处理第 {idx}/{len(qualified_stocks)} 只股票")
        print(f"{'='*80}")
        print(f"股票代码：{stock['code']}")
        print(f"股票名称：{stock['name']}")
        print(f"交易所：{stock['exchange']}")
        
        # 生成报告
        report = generate_report(stock)
        save_report(report, report_dir)
        
        reports.append(report)
        
        print(f"✓ 股票 {stock['code']} 报告模板生成完成")
    
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
    print("提示：每份报告模板已生成，可使用 OpenClaw web_search 工具填充搜索数据")

if __name__ == '__main__':
    main()
