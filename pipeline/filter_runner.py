"""
筛选执行器
封装 stock_filter.py 和 stock_filter_b2.py 的调用，收集结构化结果
支持 B1 + B2严格 + B2宽松 三种策略，去重合并后输出
"""

import sys
import os
import csv
import datetime
import logging
from pathlib import Path
from typing import List, Dict

from pipeline.models import StockFilterData, FilterResults

logger = logging.getLogger("pipeline.filter_runner")


class StockFilterRunner:
    """封装多策略筛选的执行"""

    def __init__(self, config):
        self.config = config

    def execute(self, debug=False) -> FilterResults:
        """
        执行 B1 + B2 策略筛选，返回合并去重后的结构化结果。

        Args:
            debug: 调试模式。跳过数据更新（市值快筛+API拉取），只用本地缓存跑流程。

        流程：
        1. 执行 B1 筛选（拉取日K+周K+实时数据，缓存到本地）
        2. 执行 B2 筛选（复用本地缓存的日K数据，无额外 API 调用）
        3. 合并去重，生成统一的 FilterResults
        4. 分别保存 B1 和 B2 的 CSV
        """
        import threading
        import signal

        # 确保 stock_filter.py 所在目录在 sys.path 中
        workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if workspace_root not in sys.path:
            sys.path.insert(0, workspace_root)

        from stock_filter import run_filter
        from stock_filter_b2 import run_b2_filter

        # 重新注册信号处理
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, lambda sig, frame: os._exit(0))

        today = datetime.date.today().strftime('%Y-%m-%d')

        # ── Step 1: 执行 B1 筛选 ──
        logger.info("执行 B1 策略筛选...")
        b1_raw_results = run_filter(
            strategy=getattr(self.config, 'strategy', 'b1'),
            test=False,
            mock=False,
            retry=False,
            debug=debug,
        )
        self._save_csv(b1_raw_results, today, prefix="b1")

        # 提取 B1 通过的股票列表（用于 B2 的股票池）
        # B2 使用与 B1 相同的股票池（已经过市值快筛），复用本地缓存
        b1_stock_list = []
        for item in b1_raw_results:
            if item.get('status') == 'success':
                b1_stock_list.append(item.get('stock', {}))

        # ── Step 2: 执行 B2 筛选（复用 B1 已缓存的日K数据）──
        logger.info("执行 B2 策略筛选（使用本地缓存数据）...")
        b2_raw_results = run_b2_filter(stock_list=b1_stock_list, mock=False)
        self._save_b2_csv(b2_raw_results, today)

        # ── Step 3: 合并去重 ──
        total_scanned = len(b1_raw_results)
        merged_stocks = self._merge_results(b1_raw_results, b2_raw_results)

        # ── Step 4: 注入自选股白名单 ──
        watchlist_codes = self._load_watchlist()
        existing_codes = {s.code for s in merged_stocks}
        watchlist_added = 0
        for code in watchlist_codes:
            if code in existing_codes:
                for s in merged_stocks:
                    if s.code == code and "自选" not in s.tags:
                        s.tags.append("自选")
            else:
                merged_stocks.append(StockFilterData(
                    code=code,
                    name=code,
                    exchange="",
                    result=True,
                    tags=["自选"],
                    details={},
                ))
                watchlist_added += 1
        if watchlist_codes:
            logger.info("自选股白名单: %d 只（%s），新增 %d 只",
                        len(watchlist_codes), ", ".join(watchlist_codes), watchlist_added)
            merged_stocks.sort(key=lambda s: 0 if "自选" in s.tags else 1)

        logger.info(
            "筛选合并完成: B1 通过 %d 只, B2严格 %d 只, B2宽松 %d 只, 自选 %d 只, 去重后共 %d 只",
            sum(1 for r in b1_raw_results if r.get('result')),
            sum(1 for r in b2_raw_results if r.get('strict_result')),
            sum(1 for r in b2_raw_results if r.get('loose_result')),
            watchlist_added,
            len(merged_stocks),
        )

        return FilterResults(
            date=today,
            total_scanned=total_scanned,
            stocks=merged_stocks,
        )

    def _merge_results(
        self,
        b1_results: List[dict],
        b2_results: List[dict],
    ) -> List[StockFilterData]:
        """
        合并 B1 和 B2 的筛选结果，按 stock_code 去重。
        一只股票可能同时满足多个策略，tags 累加。
        """
        # 以 code 为 key 的合并字典
        merged: Dict[str, StockFilterData] = {}

        # 处理 B1 结果
        for item in b1_results:
            if not item.get('result', False):
                continue
            if item.get('status') != 'success':
                continue

            stock_info = item.get('stock', {})
            code = stock_info.get('code', '')
            if not code:
                continue

            details = item.get('details', {})
            stock_data = StockFilterData(
                code=code,
                name=stock_info.get('name', ''),
                exchange=stock_info.get('exchange', ''),
                result=True,
                tags=['B1'],
                details=details,
            )
            merged[code] = stock_data

        # 处理 B2 结果
        for item in b2_results:
            strict = item.get('strict_result', False)
            loose = item.get('loose_result', False)
            if not strict and not loose:
                continue
            if item.get('status') != 'success':
                continue

            stock_info = item.get('stock', {})
            code = stock_info.get('code', '')
            if not code:
                continue

            b2_details = item.get('details', {})
            b2_tags = []
            if strict:
                b2_tags.append('B2严格')
            if loose:
                b2_tags.append('B2宽松')

            if code in merged:
                # 已有 B1 结果，追加 B2 的 tags 和 details
                merged[code].tags.extend(b2_tags)
                merged[code].details.update(b2_details)
            else:
                # 仅 B2 通过，B1 未通过
                stock_data = StockFilterData(
                    code=code,
                    name=stock_info.get('name', ''),
                    exchange=stock_info.get('exchange', ''),
                    result=True,
                    tags=b2_tags,
                    details=b2_details,
                )
                merged[code] = stock_data

        # 排序：纯B2严格 > B2严格+宽松 > 纯B2宽松 > B1按总分降序
        def _sort_key(stock: StockFilterData):
            has_strict = 'B2严格' in stock.tags
            has_loose = 'B2宽松' in stock.tags
            if has_strict and not has_loose:
                priority = 300  # 纯B2严格
            elif has_strict and has_loose:
                priority = 200  # B2严格+宽松
            elif has_loose:
                priority = 100  # 纯B2宽松
            else:
                priority = 0    # 纯B1
            # B1 总分作为次级排序（0-4分）
            b1_score = stock.details.get('新增条件总分', 0) if 'B1' in stock.tags else 0
            return (-priority, -b1_score)

        result_list = list(merged.values())
        result_list.sort(key=_sort_key)
        return result_list

    def _save_csv(self, raw_results: list, date: str, prefix: str = "b1"):
        """保存 B1 筛选结果为 CSV 文件"""
        output_dir = Path(self.config.report_output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_path = output_dir / f"{prefix}_filtered_{timestamp}.csv"

        # 收集所有字段
        all_fields = ['股票代码', '股票名称', '交易所', '状态', '结果', 'message']
        for item in raw_results:
            all_fields_set = set(all_fields)
            for key in item.get('details', {}).keys():
                if key not in all_fields_set:
                    all_fields.append(key)
                    all_fields_set.add(key)

        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction='ignore')
            writer.writeheader()
            for item in raw_results:
                stock = item.get('stock', {})
                row = {
                    '股票代码': stock.get('code', ''),
                    '股票名称': stock.get('name', ''),
                    '交易所': stock.get('exchange', ''),
                    '状态': '成功' if item.get('status') == 'success' else '错误',
                    '结果': '符合' if item.get('result') else '不符合',
                    'message': item.get('message', ''),
                }
                row.update(item.get('details', {}))
                writer.writerow(row)

        print(f"筛选 CSV 已保存: {csv_path}")

    def _save_b2_csv(self, b2_results: list, date: str):
        """保存 B2 筛选结果为 CSV 文件（包含严格版和宽松版）"""
        output_dir = Path(self.config.report_output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_path = output_dir / f"b2_filtered_{timestamp}.csv"

        # 只保存有结果的（严格或宽松通过的）
        qualified = [r for r in b2_results if r.get('strict_result') or r.get('loose_result')]

        # 定义字段
        base_fields = ['股票代码', '股票名称', '交易所', '状态', 'B2严格', 'B2宽松']
        detail_fields = set()
        for item in qualified:
            for key in item.get('details', {}).keys():
                detail_fields.add(key)
        # 排序 detail_fields 以保持一致性
        sorted_detail_fields = sorted(detail_fields)
        all_fields = base_fields + sorted_detail_fields

        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction='ignore')
            writer.writeheader()
            for item in qualified:
                stock = item.get('stock', {})
                row = {
                    '股票代码': stock.get('code', ''),
                    '股票名称': stock.get('name', ''),
                    '交易所': stock.get('exchange', ''),
                    '状态': '成功' if item.get('status') == 'success' else '错误',
                    'B2严格': '符合' if item.get('strict_result') else '不符合',
                    'B2宽松': '符合' if item.get('loose_result') else '不符合',
                }
                row.update(item.get('details', {}))
                writer.writerow(row)

        print(f"B2 筛选 CSV 已保存: {csv_path}")
        # 同时保存全量结果（包含不符合的）
        csv_path_all = output_dir / f"b2_all_{timestamp}.csv"
        with open(csv_path_all, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction='ignore')
            writer.writeheader()
            for item in b2_results:
                if item.get('status') != 'success':
                    continue
                stock = item.get('stock', {})
                row = {
                    '股票代码': stock.get('code', ''),
                    '股票名称': stock.get('name', ''),
                    '交易所': stock.get('exchange', ''),
                    '状态': '成功',
                    'B2严格': '符合' if item.get('strict_result') else '不符合',
                    'B2宽松': '符合' if item.get('loose_result') else '不符合',
                }
                row.update(item.get('details', {}))
                writer.writerow(row)

    def _load_watchlist(self) -> List[str]:
        import json
        watchlist_path = Path(__file__).parent / "watchlist.json"
        if not watchlist_path.exists():
            return []
        try:
            with open(watchlist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            codes = data.get("stocks", [])
            return [c.strip() for c in codes if c.strip()]
        except Exception as e:
            logger.warning("加载自选股白名单失败: %s", e)
            return []
