"""只读数据收集器 - 从 CSV/报告/结果中收集策略数据"""

import csv
import logging
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict
from typing import Dict, List, Optional

from strategy_researcher.config import RESEARCHER_CONFIG

logger = logging.getLogger("strategy_researcher.collector")


class DataCollector:
    """从现有数据源收集策略分析所需的数据（只读）"""

    def __init__(self):
        self.reports_dir = Path(RESEARCHER_CONFIG["reports_dir"])

    def get_latest_b1_csv(self) -> Optional[Dict]:
        """获取最新的 B1 筛选 CSV 数据"""
        files = sorted(self.reports_dir.glob("b1_filtered_*.csv"), reverse=True)
        if not files:
            return None
        return self._parse_b1_csv(files[0])

    def get_latest_b2_csv(self) -> Optional[Dict]:
        """获取最新的 B2 筛选 CSV 数据"""
        files = sorted(self.reports_dir.glob("b2_filtered_*.csv"), reverse=True)
        if not files:
            return None
        return self._parse_b2_csv(files[0])

    def get_b1_history(self, days: int = 7) -> List[Dict]:
        """获取最近 N 天的 B1 数据"""
        files = sorted(self.reports_dir.glob("b1_filtered_*.csv"), reverse=True)[:days]
        return [self._parse_b1_csv(f) for f in files if f.exists()]

    def collect_today(self) -> Dict:
        """收集今日所有数据，供 researcher 分析"""
        b1 = self.get_latest_b1_csv()
        b2 = self.get_latest_b2_csv()

        result = {
            "date": date.today().isoformat(),
            "b1": b1,
            "b2": b2,
            "current_prices": {},
        }

        # 从 B1 CSV 中提取所有股票的当前价格（用于跨天验证）
        if b1 and b1.get("all_rows"):
            for row in b1["all_rows"]:
                code = row.get("股票代码", "")
                price = row.get("收盘价", "")
                if code and price:
                    try:
                        result["current_prices"][code] = float(price)
                    except (ValueError, TypeError):
                        pass

        return result

    def _parse_b1_csv(self, filepath: Path) -> Dict:
        """解析 B1 CSV 文件"""
        with open(filepath, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        qualified = [r for r in rows if r.get("结果") == "符合"]
        total = len(rows)

        # 分数分布
        score_dist = defaultdict(int)
        for r in qualified:
            score_dist[r.get("新增条件总分", "?")] += 1

        # 全市场涨幅
        all_changes = []
        for r in rows:
            if r.get("状态") == "成功":
                try:
                    c = float(r.get("涨幅", 0))
                    if c != 0:
                        all_changes.append(c)
                except (ValueError, TypeError):
                    pass

        market_avg = sum(all_changes) / len(all_changes) if all_changes else 0
        market_up_pct = (
            sum(1 for c in all_changes if c > 0) / len(all_changes) * 100
            if all_changes
            else 0
        )

        # 提取通过股票的详细信息
        signals = []
        for r in qualified:
            try:
                signals.append({
                    "code": r.get("股票代码", ""),
                    "name": r.get("股票名称", ""),
                    "price": float(r.get("收盘价", 0)),
                    "score": int(float(r.get("新增条件总分", 0))),
                    "j_value": float(r.get("J", 0)),
                    "change_pct": float(r.get("涨幅", 0)),
                    "change_30d": float(r.get("30天涨幅", 0)) if r.get("30天涨幅") else None,
                })
            except (ValueError, TypeError):
                continue

        return {
            "filepath": str(filepath),
            "filename": filepath.name,
            "total_scanned": total,
            "qualified_count": len(qualified),
            "score_distribution": dict(score_dist),
            "market_avg_change": round(market_avg, 2),
            "market_up_pct": round(market_up_pct, 1),
            "signals": signals,
            "all_rows": rows,
        }

    def _parse_b2_csv(self, filepath: Path) -> Dict:
        """解析 B2 CSV 文件"""
        with open(filepath, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        strict = [r for r in rows if r.get("B2严格") == "符合"]
        loose = [r for r in rows if r.get("B2宽松") == "符合"]

        # 提取信号
        signals = []
        for r in rows:
            if r.get("B2严格") == "符合" or r.get("B2宽松") == "符合":
                tags = []
                if r.get("B2严格") == "符合":
                    tags.append("B2严格")
                if r.get("B2宽松") == "符合":
                    tags.append("B2宽松")
                try:
                    signals.append({
                        "code": r.get("股票代码", ""),
                        "name": r.get("股票名称", ""),
                        "price": float(r.get("收盘价", 0)),
                        "tags": tags,
                        "j_value": float(r.get("B2_J", 0)),
                        "j_last": float(r.get("B2_J_LAST", 0)),
                        "change_pct": float(r.get("B2_涨幅%", 0)),
                        "volume_ratio": float(r.get("B2_放量比", 0)),
                    })
                except (ValueError, TypeError):
                    continue

        return {
            "filepath": str(filepath),
            "filename": filepath.name,
            "strict_count": len(strict),
            "loose_count": len(loose),
            "signals": signals,
        }
