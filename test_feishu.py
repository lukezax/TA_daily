"""
本地测试：读取已有 CSV 文件，把符合条件的行发送到飞书
用法：python test_feishu.py [csv文件路径]
"""
import sys
import csv
from feishu_notify import send_b1_results

csv_file = sys.argv[1] if len(sys.argv) > 1 else "b1_filtered_stocks_20260317_024022.csv"

results = []
with open(csv_file, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get("结果") != "符合":
            continue
        details = {}
        for k, v in row.items():
            if k in ("股票代码", "股票名称", "交易所", "状态", "结果", "message"):
                continue
            if v == "" or v is None:
                details[k] = None
            elif v in ("True", "False"):
                details[k] = v == "True"
            else:
                try:
                    details[k] = float(v)
                except ValueError:
                    details[k] = v
        results.append({
            "stock": {
                "code": row["股票代码"],
                "name": row["股票名称"],
                "exchange": row["交易所"],
            },
            "result": True,
            "status": "success",
            "message": row.get("message", ""),
            "details": details,
        })

print(f"读取到 {len(results)} 条符合记录，开始发送...")
send_b1_results(results)
