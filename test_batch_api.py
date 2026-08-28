#!/usr/bin/env python3
"""
测试批量分析 API
"""
import requests
import json
from datetime import datetime

API_BASE = "http://localhost:8000"

# 1. 登录获取 token
print("[1/3] 登录获取 Token...")
login_resp = requests.post(f"{API_BASE}/api/auth/login", json={
    "username": "admin",
    "password": "admin123"
})
print(f"登录响应状态码：{login_resp.status_code}")
print(f"登录响应内容：{login_resp.text[:500]}")

if login_resp.status_code == 200:
    data = login_resp.json()
    token = data.get("data", {}).get("access_token")
    print(f"✓ 获取到 Token: {token[:50]}...")
    
    # 2. 提交批量分析
    print("\n[2/3] 提交批量分析任务...")
    batch_payload = {
        "title": "测试批量分析",
        "description": "首批测试",
        "symbols": ["600575.SH", "600025.SH", "600886.SH"],
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
    
    batch_resp = requests.post(
        f"{API_BASE}/api/analysis/batch",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=batch_payload
    )
    print(f"批量分析响应状态码：{batch_resp.status_code}")
    print(f"批量分析响应内容：{batch_resp.text}")
    
    # 3. 检查任务状态
    print("\n[3/3] 检查任务状态...")
    task_ids = json.loads(batch_resp.text)
    
else:
    print("❌ 登录失败")
