"""
数据预热器
在筛选完成后、AI分析前，将筛选阶段已获取的K线数据写入 TradingAgents 的 MongoDB，
确保分析阶段能从本地缓存命中，不依赖外部数据源。

数据源优先级：先尝试免费源（tushare/akshare/baostock），全失败再用 zhitu 兜底。
"""

import json
import logging
from pathlib import Path
from typing import List

from pipeline.models import StockFilterData

logger = logging.getLogger("pipeline.data_preheater")

# stock_data 目录（Pipeline筛选阶段拉取的数据存放位置）
STOCK_DATA_DIR = Path("stock_data")


class DataPreheater:
    """将筛选阶段的K线数据预热到 TradingAgents MongoDB"""

    def __init__(self):
        self._db = None

    def _get_db(self):
        """获取 MongoDB 连接"""
        if self._db is None:
            try:
                import pymongo
                import os
                host = os.getenv("MONGODB_HOST", "localhost")
                port = int(os.getenv("MONGODB_PORT", "27017"))
                username = os.getenv("MONGODB_USERNAME", "admin")
                password = os.getenv("MONGODB_PASSWORD", "tradingagents123")
                database = os.getenv("MONGODB_DATABASE", "tradingagentscn")
                auth_source = os.getenv("MONGODB_AUTH_SOURCE", "admin")

                client = pymongo.MongoClient(
                    host=host, port=port,
                    username=username, password=password,
                    authSource=auth_source,
                    serverSelectionTimeoutMS=5000,
                )
                self._db = client[database]
                # 验证连接
                self._db.command("ping")
            except Exception as e:
                logger.warning(f"⚠️ MongoDB 连接失败: {e}，跳过数据预热")
                self._db = None
        return self._db

    def preheat(self, stocks: List[StockFilterData]) -> int:
        """
        预热通过股票的数据到 MongoDB

        Args:
            stocks: 筛选通过的股票列表

        Returns:
            成功预热的股票数量
        """
        db = self._get_db()
        if db is None:
            logger.warning("⚠️ 数据预热跳过（MongoDB 不可用）")
            return 0

        collection = db.stock_daily_quotes
        success_count = 0
        total_records = 0

        for stock in stocks:
            code = stock.code  # 如 000519.SZ
            code6 = code.split(".")[0]

            # 从本地 stock_data 读取日K数据
            local_file = STOCK_DATA_DIR / f"{code}_d.json"
            if not local_file.exists():
                logger.debug(f"  {code}: 本地日K文件不存在，跳过")
                continue

            try:
                with open(local_file, "r", encoding="utf-8") as f:
                    file_data = json.load(f)

                kline_data = file_data.get("data", [])
                if not kline_data or len(kline_data) < 10:
                    logger.debug(f"  {code}: 本地数据不足({len(kline_data)}条)，跳过")
                    continue

                # 转换为 MongoDB 格式并写入
                records = []
                for row in kline_data:
                    # zhitu 格式: {t, o, h, l, c, v, a, pc, sf}
                    trade_date = str(row.get("t", ""))[:10].replace("-", "")
                    if not trade_date or len(trade_date) != 8:
                        continue

                    records.append({
                        "symbol": code6,
                        "trade_date": trade_date,
                        "period": "daily",
                        "open": row.get("o"),
                        "high": row.get("h"),
                        "low": row.get("l"),
                        "close": row.get("c"),
                        "volume": row.get("v"),
                        "amount": row.get("a"),
                        "pre_close": row.get("pc"),
                        "data_source": "zhitu",
                    })

                if records:
                    # 使用 upsert 避免重复
                    from pymongo import UpdateOne
                    ops = [
                        UpdateOne(
                            {"symbol": r["symbol"], "trade_date": r["trade_date"], "period": r["period"]},
                            {"$set": r},
                            upsert=True,
                        )
                        for r in records
                    ]
                    result = collection.bulk_write(ops, ordered=False)
                    total_records += len(records)
                    success_count += 1

            except Exception as e:
                logger.warning(f"  {code}: 预热失败 - {e}")
                continue

        # 确保索引存在
        try:
            collection.create_index(
                [("symbol", 1), ("trade_date", 1), ("period", 1), ("data_source", 1)],
                background=True,
            )
        except Exception:
            pass

        logger.info(
            f"数据预热完成: {success_count}/{len(stocks)} 只股票，共 {total_records} 条K线记录写入 MongoDB"
        )
        return success_count

    def preheat_indicators(self, stocks: List[StockFilterData]) -> int:
        """
        预热技术指标（MACD/KDJ/BOLL）到 MongoDB
        使用 zhitu API 获取（作为兜底，免费源获取不到时才调用）

        Args:
            stocks: 筛选通过的股票列表

        Returns:
            成功预热的股票数量
        """
        db = self._get_db()
        if db is None:
            return 0

        import sys
        import os
        ta_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "TradingAgents-CN")
        if ta_path not in sys.path:
            sys.path.insert(0, ta_path)

        try:
            from app.services.data_sources.zhitu_adapter import ZhituAdapter
            adapter = ZhituAdapter()
            if not adapter.is_available():
                logger.warning("⚠️ zhitu API 不可用，跳过指标预热")
                return 0
        except Exception as e:
            logger.warning(f"⚠️ 导入 zhitu adapter 失败: {e}")
            return 0

        collection = db.stock_indicators
        success_count = 0

        for stock in stocks:
            code = stock.code
            code6 = code.split(".")[0]

            try:
                # 获取 MACD
                macd_data = adapter.get_macd(code6, period="d", limit=60)
                # 获取 KDJ
                kdj_data = adapter.get_kdj(code6, period="d", limit=60)
                # 获取 BOLL
                boll_data = adapter.get_boll(code6, period="d", limit=60)

                if not macd_data and not kdj_data and not boll_data:
                    continue

                # 合并写入
                from pymongo import UpdateOne
                ops = []

                for dataset, indicator_type in [
                    (macd_data, "macd"),
                    (kdj_data, "kdj"),
                    (boll_data, "boll"),
                ]:
                    if not dataset:
                        continue
                    for row in dataset:
                        trade_date = str(row.get("time", ""))[:10].replace("-", "")
                        if not trade_date or len(trade_date) != 8:
                            continue
                        doc = {
                            "symbol": code6,
                            "trade_date": trade_date,
                            "indicator": indicator_type,
                            "data_source": "zhitu",
                        }
                        doc.update({k: v for k, v in row.items() if k != "time"})
                        ops.append(UpdateOne(
                            {"symbol": code6, "trade_date": trade_date, "indicator": indicator_type},
                            {"$set": doc},
                            upsert=True,
                        ))

                if ops:
                    collection.bulk_write(ops, ordered=False)
                    success_count += 1

            except Exception as e:
                logger.warning(f"  {code}: 指标预热失败 - {e}")
                continue

        # 确保索引
        try:
            collection.create_index(
                [("symbol", 1), ("trade_date", 1), ("indicator", 1)],
                background=True,
            )
        except Exception:
            pass

        logger.info(f"指标预热完成: {success_count}/{len(stocks)} 只股票")
        return success_count
