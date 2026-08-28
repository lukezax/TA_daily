#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量股票分析脚本 v2.0
使用 TradingAgents-CN 进行多智能体分析
"""

import csv
import os
import sys
import json
from pathlib import Path
from datetime import datetime
import subprocess

# 配置
CSV_FILE = "/home/lukezax/workspace/stock/b1_filtered_stocks_20260402_021729.csv"
OUTPUT_DIR = "/home/lukezax/workspace/stock/analysis_reports"
TRADING_AGENTS_PATH = "/home/lukezax/workspace/TradingAgents-CN"
ENV_FILE = f"{TRADING_AGENTS_PATH}/.env"
TRADING_AGENTS_VENV = "/home/lukezax/workspace/TradingAgents-CN/venv"

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
                    'open_price': float(row['开盘价']),
                    'high_price': float(row['最高价']),
                    'low_price': float(row['最低价']),
                    'volume': float(row['volume']),
                    'amount': float(row['amount']),
                    'total_market_cap': float(row['总市值']),
                    'circulating_market_cap': float(row['流通市值']),
                    'message': row.get('message', '处理成功')
                })
    return stocks

def check_dependencies():
    """检查必要依赖"""
    print("\n[检查依赖] Checking dependencies...")
    
    # 检查 Python 版本
    import sys
    if sys.version_info < (3, 8):
        print("❌ Python 版本过低，需要 3.8 或更高")
        return False
    
    # 检查 required packages (使用系统 Python)
    required_packages = ['typer', 'dashscope', 'openai']
    for pkg in required_packages:
        try:
            __import__(pkg)
            print(f"  ✓ {pkg}")
        except ImportError:
            print(f"  ❌ {pkg} 未安装")
            return False
    
    # 检查虚拟环境中的 Python
    venv_python = os.path.join(TRADING_AGENTS_VENV, "bin", "python3")
    if not os.path.exists(venv_python):
        print(f"❌ 虚拟环境不存在：{venv_python}")
        return False
    
    # 测试虚拟环境中的 Python 是否能导入 tradingagents
    test_cmd = [venv_python, "-c", "import tradingagents; print('OK')"]
    result = subprocess.run(test_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ 虚拟环境中的 tradingagents 模块导入失败：{result.stderr}")
        return False
    
    print("✓ 虚拟环境配置正确")
    return True
    
def run_single_analysis(stock, config):
    """运行单只股票的分析"""
    print(f"\n  分析：{stock['code']} {stock['name']}")
    
    # 准备股票代码
    ticker = stock['code']
    
    # 使用虚拟环境中的 Python 解释器
    venv_python = os.path.join(TRADING_AGENTS_VENV, "bin", "python3")
    
    # 调用 TradingAgents-CN CLI
    cmd = [
        venv_python,
        "-m", "tradingagents.cli",
        "analyze",
        "--ticker", ticker,
        "--llm-provider", config['llm_provider'],
        "--analysts", ",".join(config['analysts']),
        "--results-dir", OUTPUT_DIR
    ]
    
    print(f"  执行命令：{' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=TRADING_AGENTS_PATH,
            capture_output=True,
            text=True,
            timeout=3600  # 1 小时超时
        )
        
        if result.returncode == 0:
            print(f"  ✓ 分析完成")
            return True
        else:
            # 显示错误信息的前 500 个字符
            error_msg = result.stderr[:500] if result.stderr else "无错误信息"
            print(f"  ❌ 分析失败：{error_msg}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  分析超时")
        return False
    except Exception as e:
        print(f"  ❌ 错误：{str(e)}")
        return False

def generate_summary_report(stocks, results_dir):
    """生成汇总报告"""
    report_path = os.path.join(results_dir, "summary_report.md")
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# 批量股票分析报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**股票数量**: {len(stocks)}\n\n")
        
        f.write("## 股票列表\n\n")
        f.write("| 序号 | 股票代码 | 股票名称 | 交易所 | 现价 | 总市值 |\n")
        f.write("|------|----------|----------|--------|------|--------|\n")
        
        for i, stock in enumerate(stocks, 1):
            market_cap = stock['total_market_cap'] / 1e8  # 转换为亿
            f.write(f"| {i} | {stock['code']} | {stock['name']} | {stock['exchange']} | {stock['close_price']:.2f} | {market_cap:.2f}亿 |\n")
        
        f.write("\n## 分析说明\n\n")
        f.write("本报告基于 TradingAgents-CN 多智能体分析框架生成。\n\n")
        f.write("### 多智能体分析\n\n")
        f.write("TradingAgents-CN 使用多个专业分析师 AI 智能体进行协作分析：\n\n")
        f.write("1. **市场分析师** - 技术分析、K 线形态、成交量分析\n")
        f.write("2. **基本面分析师** - 财务报表、估值指标、行业对比\n")
        f.write("3. **消息分析师** - 新闻舆情、政策影响、行业消息\n")
        f.write("4. **交易策略分析师** - 买卖点建议、风险控制、仓位管理\n\n")
        f.write("### 分析流程\n\n")
        f.write("1. 数据收集 - 获取实时行情、财务数据、新闻资讯\n")
        f.write("2. 多智能体协作 - 各分析师独立分析并讨论\n")
        f.write("3. 综合评估 - 生成综合投资建议和风险提示\n")
        f.write("4. 报告生成 - 输出详细分析报告\n\n")
        
        f.write("## 风险提示\n")
        f.write("⚠️ 本分析结果仅供参考，不构成投资建议。\n")
        f.write("投资有风险，入市需谨慎。\n")
    
    print(f"✓ 汇总报告已生成：{report_path}")

def main():
    print("=" * 70)
    print("批量股票分析脚本 v2.0 - TradingAgents-CN")
    print("=" * 70)
    
    # 1. 读取筛选结果
    print(f"\n[1/5] 读取筛选结果：{CSV_FILE}")
    if not os.path.exists(CSV_FILE):
        print(f"❌ 文件不存在：{CSV_FILE}")
        sys.exit(1)
    
    stocks = read_filtered_stocks(CSV_FILE)
    print(f"✓ 找到 {len(stocks)} 只符合条件的股票")
    
    # 显示股票列表
    print("\n符合条件的股票:")
    print("-" * 70)
    for i, stock in enumerate(stocks, 1):
        market_cap = stock['total_market_cap'] / 1e8
        print(f"{i:2}. {stock['code']} {stock['name']:12} ({stock['exchange']}) - 现价：{stock['close_price']:.2f}  总市值：{market_cap:.2f}亿")
    
    # 2. 检查依赖
    print("\n[2/5] 检查依赖")
    if not check_dependencies():
        print("❌ 依赖检查失败，请安装所需包后重试")
        sys.exit(1)
    
    # 3. 创建输出目录
    print(f"\n[3/5] 准备输出目录：{OUTPUT_DIR}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("✓ 输出目录已就绪")
    
    # 4. 运行分析
    print(f"\n[4/5] 开始分析 {len(stocks)} 只股票")
    print("-" * 70)
    
    # 默认配置
    config = {
        'llm_provider': 'dashscope',  # 使用阿里百炼
        'analysts': ['市场分析师', '基本面分析师', '消息分析师', '交易策略分析师']
    }
    
    # 运行分析
    success_count = 0
    fail_count = 0
    
    for i, stock in enumerate(stocks, 1):
        print(f"\n[{i}/{len(stocks)}] 分析进度")
        result = run_single_analysis(stock, config)
        if result:
            success_count += 1
        else:
            fail_count += 1
        
        # 每分析 5 只股票显示一次进度
        if i % 5 == 0:
            print(f"\n进度：{i}/{len(stocks)} ({success_count}成功，{fail_count}失败)")
    
    # 5. 生成汇总报告
    print(f"\n[5/5] 生成汇总报告")
    generate_summary_report(stocks, OUTPUT_DIR)
    
    # 总结
    print("\n" + "=" * 70)
    print("✓ 分析完成!")
    print("=" * 70)
    print(f"\n结果统计:")
    print(f"  - 成功：{success_count} 只")
    print(f"  - 失败：{fail_count} 只")
    print(f"  - 总计：{len(stocks)} 只")
    print(f"\n输出目录：{OUTPUT_DIR}")
    print(f"汇总报告：{os.path.join(OUTPUT_DIR, 'summary_report.md')}")

if __name__ == "__main__":
    main()
