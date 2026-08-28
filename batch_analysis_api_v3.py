#!/usr/bin/env python3
"""
批量股票分析脚本 v3.0 - 使用 API 方式
Batch Stock Analysis Script v3.0 - Using API
"""

import json
import csv
import time
import requests
from pathlib import Path
from datetime import datetime

# API 配置
API_BASE_URL = "http://localhost:8000"

# 输出目录
OUTPUT_DIR = Path("/home/lukezax/workspace/stock/analysis_reports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def get_api_token():
    """获取 API Token"""
    try:
        response = requests.post(f"{API_BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        if response.status_code == 200:
            data = response.json()
            return data.get("data", {}).get("access_token")
    except Exception as e:
        print(f"❌ 获取 API Token 失败：{e}")
    return None

def submit_batch_analysis(tickers, title="批量分析", description=None):
    """提交批量分析任务"""
    token = get_api_token()
    if not token:
        return None
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "title": title,
        "description": description,
        "symbols": tickers,
        "parameters": {
            "market_type": "A 股",
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "research_depth": "标准",  # 3 级标准分析
            "selected_analysts": ["market", "fundamentals", "news", "social"],
            "include_sentiment": True,
            "include_risk": True,
            "language": "zh-CN"
        }
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/analysis/batch",
            headers=headers,
            json=payload
        )
        return response.json()
    except Exception as e:
        print(f"❌ 提交批量分析失败：{e}")
        return None

def read_filtered_stocks(csv_file):
    """读取筛选结果"""
    tickers = []
    stock_info = []
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get('股票代码') or row.get('ticker') or row.get('stock_code')
            if ticker:
                tickers.append(ticker)
                stock_info.append(row)
    
    return tickers, stock_info

def main():
    print("=" * 80)
    print("批量股票分析脚本 v3.0 - TradingAgents-CN (API 方式)")
    print("=" * 80)
    
    # 读取筛选结果
    csv_file = "/home/lukezax/workspace/stock/b1_filtered_stocks_20260402_021729.csv"
    if not Path(csv_file).exists():
        print(f"❌ 文件不存在：{csv_file}")
        return
    
    print(f"\n[1/5] 读取筛选结果：{csv_file}")
    tickers, stock_info = read_filtered_stocks(csv_file)
    print(f"✓ 找到 {len(tickers)} 只符合条件的股票")
    
    if not tickers:
        print("❌ 没有符合条件的股票")
        return
    
    print("\n符合条件的股票:")
    for i, (ticker, info) in enumerate(zip(tickers, stock_info), 1):
        print(f"  {i:2d}. {ticker}")
    
    # 分批提交（最多 10 个）
    batch_size = 10
    all_results = []
    
    print(f"\n[2/5] 检查 API 连接")
    response = requests.get(f"{API_BASE_URL}/api/health")
    if response.status_code == 200:
        print("✓ API 连接正常")
    else:
        print("❌ API 连接失败")
        return
    
    print(f"\n[3/5] 提交批量分析任务（每批{batch_size}个）")
    batch_num = 0
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        batch_num += 1
        print(f"\n  提交批次 {batch_num}: {len(batch)} 个股票")
        print(f"    股票：{', '.join(batch)}")
        
        title = f"批量分析批次{batch_num}"
        description = f"分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        result = submit_batch_analysis(batch, title=title, description=description)
        
        if result and result.get("success"):
            batch_id = result.get("batch_id")
            task_ids = result.get("task_ids", [])
            print(f"  ✓ 批次提交成功")
            print(f"    批次 ID: {batch_id}")
            print(f"    任务数：{len(task_ids)}")
            print(f"    状态：{result.get('status', 'submitted')}")
            
            all_results.append({
                "batch_number": batch_num,
                "batch_id": batch_id,
                "title": title,
                "task_ids": task_ids,
                "symbols": batch
            })
            
            time.sleep(2)  # 等待一下
        else:
            print(f"  ❌ 批次提交失败：{result}")
            time.sleep(2)
    
    print(f"\n[4/5] 等待分析完成...")
    print("由于分析需要较长时间，建议通过以下方式查看结果:")
    print("  1. 访问 http://localhost:8000/dashboard 查看任务状态")
    print("  2. 使用 'python3 check_batch_status.py' 脚本检查进度")
    print("  3. 完成后访问 '/home/lukezax/workspace/stock/analysis_reports/' 查看报告")
    
    print(f"\n[5/5] 生成汇总信息")
    summary_file = OUTPUT_DIR / "batch_summary.md"
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("# 批量分析汇总\n\n")
        f.write(f"**提交时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## 批次列表\n\n")
        
        for batch in all_results:
            f.write(f"### 批次 {batch['batch_number']}\n\n")
            f.write(f"- **批次 ID**: {batch['batch_id']}\n")
            f.write(f"- **标题**: {batch['title']}\n")
            f.write(f"- **任务数**: {len(batch['task_ids'])}\n")
            f.write(f"- **股票代码**: {', '.join(batch['symbols'])}\n\n")
    
    print(f"✓ 汇总信息已生成：{summary_file}")
    print(f"\n======================================================================")
    print(f"✓ 批量分析提交完成!")
    print(f"======================================================================")
    print(f"\n结果统计:")
    print(f"  - 提交批次：{len(all_results)}")
    print(f"  - 总任务数：{sum(len(r['task_ids']) for r in all_results)}")
    print(f"  - 总股票数：{len(tickers)}")
    print(f"\n输出目录：{OUTPUT_DIR}")
    print(f"汇总信息：{summary_file}")

if __name__ == "__main__":
    main()
