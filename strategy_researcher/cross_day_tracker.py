"""跨天收益追踪 - 记录触发信号，N天后验证实际收益"""

import json
import logging
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

from strategy_researcher.config import RESEARCHER_CONFIG

logger = logging.getLogger("strategy_researcher.tracker")

WIKI_DIR = Path(RESEARCHER_CONFIG["wiki_dir"])
TRACKING_DIR = WIKI_DIR / "tracking"
PENDING_FILE = TRACKING_DIR / "pending.json"
VERIFIED_DIR = TRACKING_DIR / "verified"


class CrossDayTracker:
    """跨天收益追踪器"""

    def __init__(self):
        TRACKING_DIR.mkdir(parents=True, exist_ok=True)
        VERIFIED_DIR.mkdir(parents=True, exist_ok=True)
        self.hold_days = RESEARCHER_CONFIG["hold_days"]

    def record_today_signals(self, b1_data: Optional[Dict], b2_data: Optional[Dict]):
        """记录今天触发的所有信号到 pending"""
        today = date.today().isoformat()
        pending = self._load_pending()

        # 避免重复记录（同一天的信号只记录一次）
        existing_dates = {r["buy_date"] for r in pending}
        if today in existing_dates:
            logger.info("今日信号已记录，跳过")
            return

        new_records = []

        # B1 信号
        if b1_data and b1_data.get("signals"):
            for s in b1_data["signals"]:
                if s["price"] > 0:
                    new_records.append({
                        "code": s["code"],
                        "name": s["name"],
                        "buy_date": today,
                        "buy_price": s["price"],
                        "strategy": "B1",
                        "score": s.get("score", 0),
                        "tags": ["B1"],
                        "hold_target_days": self.hold_days,
                    })

        # B2 信号
        if b2_data and b2_data.get("signals"):
            for s in b2_data["signals"]:
                if s["price"] > 0:
                    # 检查是否已经被 B1 记录
                    existing_codes = {r["code"] for r in new_records}
                    if s["code"] in existing_codes:
                        # 追加 tag
                        for r in new_records:
                            if r["code"] == s["code"]:
                                r["tags"].extend(s.get("tags", ["B2"]))
                                break
                    else:
                        new_records.append({
                            "code": s["code"],
                            "name": s["name"],
                            "buy_date": today,
                            "buy_price": s["price"],
                            "strategy": "B2",
                            "score": 0,
                            "tags": s.get("tags", ["B2"]),
                            "hold_target_days": self.hold_days,
                        })

        pending.extend(new_records)
        self._save_pending(pending)
        logger.info("记录 %d 个新信号（B1: %d, B2: %d）",
                    len(new_records),
                    sum(1 for r in new_records if r["strategy"] == "B1"),
                    sum(1 for r in new_records if r["strategy"] == "B2"))

    def verify_pending(self, current_prices: Dict[str, float]):
        """检查 pending 中到期的记录，计算实际收益"""
        if not current_prices:
            logger.warning("无当前价格数据，跳过验证")
            return

        pending = self._load_pending()
        today = date.today()
        still_pending = []
        newly_verified = []

        for record in pending:
            buy_date = date.fromisoformat(record["buy_date"])
            hold_days = record.get("hold_target_days", self.hold_days)

            # 还没到期
            if (today - buy_date).days < hold_days:
                still_pending.append(record)
                continue

            # 到期了，尝试获取当前价格
            code = record["code"]
            sell_price = current_prices.get(code)

            if sell_price is None or sell_price <= 0:
                # 没有价格数据，继续等待（最多多等3天）
                if (today - buy_date).days < hold_days + 3:
                    still_pending.append(record)
                else:
                    # 超时放弃
                    record["sell_price"] = None
                    record["sell_date"] = today.isoformat()
                    record["return_pct"] = None
                    record["hold_days"] = (today - buy_date).days
                    record["status"] = "no_price"
                    newly_verified.append(record)
                continue

            # 计算收益
            buy_price = record["buy_price"]
            return_pct = (sell_price - buy_price) / buy_price * 100

            record["sell_price"] = sell_price
            record["sell_date"] = today.isoformat()
            record["return_pct"] = round(return_pct, 2)
            record["hold_days"] = (today - buy_date).days
            record["status"] = "verified"
            newly_verified.append(record)

        # 保存
        self._save_pending(still_pending)

        if newly_verified:
            self._save_verified(today.isoformat(), newly_verified)
            logger.info("验证 %d 个信号: 平均收益 %.2f%%",
                        len(newly_verified),
                        sum(r["return_pct"] for r in newly_verified if r["return_pct"] is not None)
                        / max(1, sum(1 for r in newly_verified if r["return_pct"] is not None)))

    def get_performance_summary(self, days: int = 30) -> Dict:
        """汇总最近 N 天的策略表现"""
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        all_verified = []

        for f in VERIFIED_DIR.glob("*.json"):
            if f.stem >= cutoff:
                try:
                    records = json.loads(f.read_text(encoding="utf-8"))
                    all_verified.extend(records)
                except (json.JSONDecodeError, IOError):
                    continue

        if not all_verified:
            return {"total": 0, "message": "暂无验证数据"}

        # 按策略+分数分组统计
        groups = defaultdict(list)
        for r in all_verified:
            if r.get("return_pct") is None:
                continue
            key = f"{r['strategy']}_{r.get('score', 0)}分"
            groups[key].append(r["return_pct"])

        summary = {
            "total": len(all_verified),
            "period_days": days,
            "by_strategy": {},
        }

        for key, returns in sorted(groups.items()):
            avg = sum(returns) / len(returns)
            pos = sum(1 for r in returns if r > 0)
            summary["by_strategy"][key] = {
                "count": len(returns),
                "avg_return": round(avg, 2),
                "win_rate": round(pos / len(returns) * 100, 1),
                "max_gain": round(max(returns), 2),
                "max_loss": round(min(returns), 2),
            }

        # 整体统计
        all_returns = [r["return_pct"] for r in all_verified if r.get("return_pct") is not None]
        if all_returns:
            summary["overall"] = {
                "count": len(all_returns),
                "avg_return": round(sum(all_returns) / len(all_returns), 2),
                "win_rate": round(sum(1 for r in all_returns if r > 0) / len(all_returns) * 100, 1),
            }

        return summary

    def get_pending_count(self) -> int:
        """获取待验证的信号数量"""
        return len(self._load_pending())

    def _load_pending(self) -> List[Dict]:
        if PENDING_FILE.exists():
            try:
                return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save_pending(self, records: List[Dict]):
        PENDING_FILE.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_verified(self, date_str: str, records: List[Dict]):
        path = VERIFIED_DIR / f"{date_str}.json"
        # 追加到已有文件
        existing = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                pass
        existing.extend(records)
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
