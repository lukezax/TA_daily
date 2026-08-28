"""
B2 策略筛选器（严格版 + 宽松版）

B2 宽松版条件：
  COND1: 前一交易日 J 值 < 0
  COND2: 涨幅 > 3.95%
  COND3: 比前一交易日放量
  COND4: 当日 J 值 < 55

B2 严格版额外条件：
  COND1: 前一交易日 J 值 < 13（更严格）
  COND5: 收阳且上影线占当日涨幅 < 20%
  COND6: C > ZXDKX
  COND7: ZXDQ > ZXDKX
"""

import sys
import os
import datetime
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple

from api import get_stock_list, get_stock_history_data
from filter import calculate_rsv, calculate_kdj, calculate_ema, calculate_ma
from config import B1_STRATEGY_CONFIG, STORAGE_CONFIG

# B2 策略参数
B2_STRATEGY_CONFIG = {
    'n': 9,           # KDJ 计算周期
    'm1': 14,         # ZXDKX 计算周期1
    'm2': 28,         # ZXDKX 计算周期2
    'm3': 57,         # ZXDKX 计算周期3
    'm4': 114,        # ZXDKX 计算周期4
    'ema_period': 10, # ZXDQ 计算周期
    'j_strict_threshold': 13,   # 严格版 J_LAST 阈值
    'j_loose_threshold': 0,     # 宽松版 J_LAST 阈值
    'change_threshold': 3.95,   # 涨幅阈值 (%)
    'j_max_threshold': 55,      # 当日 J 值上限
    'upper_shadow_ratio': 0.2,  # 上影线占涨幅比例上限（严格版）
}


def _calculate_sma(values: list, n: int, m: int) -> list:
    """
    计算 SMA(X, N, M) = (M * X + (N - M) * SMA') / N
    通达信公式中的 SMA 递推算法
    """
    if not values:
        return []
    result = [values[0]]  # 初始值
    for i in range(1, len(values)):
        sma = (m * values[i] + (n - m) * result[-1]) / n
        result.append(sma)
    return result


def _calculate_kdj_series(close_prices: list, high_prices: list, low_prices: list, n: int = 9) -> Tuple[list, list, list]:
    """
    计算完整的 KDJ 序列（通达信公式）
    RSV = (CLOSE - LLV(LOW,9)) / (HHV(HIGH,9) - LLV(LOW,9)) * 100
    K = SMA(RSV, 3, 1)
    D = SMA(K, 3, 1)
    J = 3*K - 2*D

    Returns:
        (k_series, d_series, j_series) 长度与输入相同
    """
    length = len(close_prices)
    rsv_series = []

    for i in range(length):
        if i < n - 1:
            # 数据不足 n 天时，用已有数据计算
            window_start = 0
        else:
            window_start = i - n + 1

        hh = max(high_prices[window_start:i + 1])
        ll = min(low_prices[window_start:i + 1])
        rng = hh - ll
        if rng == 0:
            rsv_series.append(50.0)
        else:
            rsv_series.append((close_prices[i] - ll) / rng * 100)

    # K = SMA(RSV, 3, 1)
    k_series = _calculate_sma(rsv_series, 3, 1)
    # D = SMA(K, 3, 1)
    d_series = _calculate_sma(k_series, 3, 1)
    # J = 3*K - 2*D
    j_series = [3 * k - 2 * d for k, d in zip(k_series, d_series)]

    return k_series, d_series, j_series


def b2_filter(stock_data: list) -> Dict[str, Any]:
    """
    对单只股票执行 B2 严格版和宽松版筛选

    Args:
        stock_data: 日K数据列表，每个元素包含 c/h/l/o/v 字段

    Returns:
        {
            'strict_result': bool,
            'loose_result': bool,
            'details': dict,  # 所有计算指标
            'conditions_strict': dict,  # 严格版各条件结果
            'conditions_loose': dict,   # 宽松版各条件结果
        }
    """
    min_data_days = max(B2_STRATEGY_CONFIG['m4'], 120)
    if len(stock_data) < min_data_days:
        return {
            'strict_result': False,
            'loose_result': False,
            'details': {},
            'conditions_strict': {},
            'conditions_loose': {},
            'error': f'数据不足：{len(stock_data)}条，需要至少{min_data_days}条'
        }

    # 提取数据
    close_prices = [item['c'] for item in stock_data]
    high_prices = [item['h'] for item in stock_data]
    low_prices = [item['l'] for item in stock_data]
    open_prices = [item['o'] for item in stock_data]
    volumes = [item['v'] for item in stock_data]

    # 计算 KDJ 完整序列
    k_series, d_series, j_series = _calculate_kdj_series(
        close_prices, high_prices, low_prices, B2_STRATEGY_CONFIG['n']
    )

    # 当日和前一日的值
    j_today = j_series[-1]
    j_last = j_series[-2]  # REF(J, 1)
    vol_today = volumes[-1]
    vol_last = volumes[-2]  # REF(VOL, 1)
    close_today = close_prices[-1]
    close_last = close_prices[-2]  # REF(CLOSE, 1)
    open_today = open_prices[-1]
    high_today = high_prices[-1]

    # 计算涨幅
    change_pct = (close_today / close_last - 1) * 100 if close_last > 0 else 0

    # 计算放量比
    volume_ratio = vol_today / vol_last if vol_last > 0 else 0

    # ── 宽松版条件 ──
    cond1_loose = j_last < B2_STRATEGY_CONFIG['j_loose_threshold']  # J_LAST < 0
    cond2 = change_pct > B2_STRATEGY_CONFIG['change_threshold']      # 涨幅 > 3.95%
    cond3 = vol_today > vol_last                                      # 放量
    cond4 = j_today < B2_STRATEGY_CONFIG['j_max_threshold']          # J < 55

    loose_result = cond1_loose and cond2 and cond3 and cond4

    # ── 严格版额外条件 ──
    cond1_strict = j_last < B2_STRATEGY_CONFIG['j_strict_threshold']  # J_LAST < 13

    # COND5: 收阳且上影线占当日涨幅 < 20%
    # C > O AND ((H-C)/(H-REF(C,1))) < 0.2
    is_yang = close_today > open_today
    upper_shadow_ratio = 0.0
    if high_today > close_last and is_yang:
        upper_shadow_ratio = (high_today - close_today) / (high_today - close_last)
    cond5 = is_yang and upper_shadow_ratio < B2_STRATEGY_CONFIG['upper_shadow_ratio']

    # 计算 ZXDQ 和 ZXDKX（严格版需要）
    ema_period = B2_STRATEGY_CONFIG['ema_period']
    ema10 = calculate_ema(close_prices, ema_period)
    zxdq = None
    zxdkx = None

    if ema10 is not None:
        zxdq_series = calculate_ema(ema10, ema_period)
        if zxdq_series is not None:
            zxdq = zxdq_series[-1]

    m1 = B2_STRATEGY_CONFIG['m1']
    m2 = B2_STRATEGY_CONFIG['m2']
    m3 = B2_STRATEGY_CONFIG['m3']
    m4 = B2_STRATEGY_CONFIG['m4']
    ma14 = calculate_ma(close_prices, m1)
    ma28 = calculate_ma(close_prices, m2)
    ma57 = calculate_ma(close_prices, m3)
    ma114 = calculate_ma(close_prices, m4)

    if None not in [ma14, ma28, ma57, ma114]:
        zxdkx = (ma14[-1] + ma28[-1] + ma57[-1] + ma114[-1]) / 4

    # COND6: C > ZXDKX
    cond6 = close_today > zxdkx if zxdkx is not None else False
    # COND7: ZXDQ > ZXDKX
    cond7 = zxdq > zxdkx if (zxdq is not None and zxdkx is not None) else False

    strict_result = cond1_strict and cond2 and cond3 and cond4 and cond5 and cond6 and cond7

    # 组装 details
    details = {
        'B2_J': round(j_today, 2),
        'B2_J_LAST': round(j_last, 2),
        'B2_K': round(k_series[-1], 2),
        'B2_D': round(d_series[-1], 2),
        'B2_涨幅%': round(change_pct, 2),
        'B2_放量比': round(volume_ratio, 2),
        'B2_上影线比': round(upper_shadow_ratio, 4),
        'B2_ZXDQ': round(zxdq, 2) if zxdq is not None else None,
        'B2_ZXDKX': round(zxdkx, 2) if zxdkx is not None else None,
        'B2_收阳': is_yang,
    }

    conditions_strict = {
        'B2严_J_LAST<13': cond1_strict,
        'B2严_涨幅>3.95%': cond2,
        'B2严_放量': cond3,
        'B2严_J<55': cond4,
        'B2严_收阳且上影线<20%': cond5,
        'B2严_C>ZXDKX': cond6,
        'B2严_ZXDQ>ZXDKX': cond7,
    }

    conditions_loose = {
        'B2松_J_LAST<0': cond1_loose,
        'B2松_涨幅>3.95%': cond2,
        'B2松_放量': cond3,
        'B2松_J<55': cond4,
    }

    return {
        'strict_result': strict_result,
        'loose_result': loose_result,
        'details': details,
        'conditions_strict': conditions_strict,
        'conditions_loose': conditions_loose,
    }


def process_stock_b2(stock: dict, mock: bool = False) -> Dict[str, Any]:
    """
    处理单只股票的 B2 筛选

    Returns:
        {
            'stock': dict,
            'status': str,
            'message': str,
            'strict_result': bool,
            'loose_result': bool,
            'details': dict,
        }
    """
    try:
        # 获取日K数据（优先使用本地缓存，B1 已经拉过了）
        if mock:
            from mock_data import get_mock_stock_history_data
            history_data = get_mock_stock_history_data(stock['code'], period='d', limit=200)
        else:
            history_data = get_stock_history_data(stock['code'], period='d', limit=200, use_local=True)

        if not history_data:
            return {
                'stock': stock,
                'status': 'error',
                'message': '无法获取历史数据',
                'strict_result': False,
                'loose_result': False,
                'details': {},
            }

        filter_result = b2_filter(history_data)

        if 'error' in filter_result:
            return {
                'stock': stock,
                'status': 'error',
                'message': filter_result['error'],
                'strict_result': False,
                'loose_result': False,
                'details': {},
            }

        # 合并 details
        all_details = {}
        all_details.update(filter_result['details'])
        all_details.update(filter_result['conditions_strict'])
        all_details.update(filter_result['conditions_loose'])

        # 添加基础行情数据
        latest = history_data[-1]
        all_details['收盘价'] = latest.get('c', 0)
        all_details['开盘价'] = latest.get('o', 0)
        all_details['最高价'] = latest.get('h', 0)
        all_details['最低价'] = latest.get('l', 0)

        return {
            'stock': stock,
            'status': 'success',
            'message': '处理成功',
            'strict_result': filter_result['strict_result'],
            'loose_result': filter_result['loose_result'],
            'details': all_details,
        }

    except Exception as e:
        return {
            'stock': stock,
            'status': 'error',
            'message': f'处理失败: {str(e)}',
            'strict_result': False,
            'loose_result': False,
            'details': {},
        }


def run_b2_filter(stock_list: Optional[List[dict]] = None, mock: bool = False) -> List[Dict[str, Any]]:
    """
    执行 B2 筛选（严格版 + 宽松版）

    Args:
        stock_list: 股票列表（如果为 None，则自动获取并过滤）
        mock: 是否使用模拟数据

    Returns:
        List[dict]: 筛选结果列表
    """
    print("\n" + "=" * 60)
    print("开始 B2 策略筛选...")
    print("=" * 60)

    # 如果没有传入股票列表，自动获取
    if stock_list is None:
        if mock:
            from mock_data import get_mock_stock_list
            stock_list = get_mock_stock_list()
        else:
            stock_list = get_stock_list()

        if not stock_list:
            print("无法获取股票列表")
            return []

        # 剔除创业板、科创板和 ST 股票
        stock_list = [
            s for s in stock_list
            if not s['code'].split('.')[0].startswith(('300', '301', '302', '688'))
            and not s['name'].startswith('ST')
            and not s['name'].startswith('*ST')
        ]

    print(f"B2 筛选股票池: {len(stock_list)} 只")
    print("B2 筛选使用本地缓存数据（B1 已拉取），无额外 API 调用")

    all_results = []
    total = len(stock_list)

    # 纯本地计算，可以用较多线程
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(process_stock_b2, stock, mock): stock
            for stock in stock_list
        }
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            all_results.append(result)
            if result['strict_result'] or result['loose_result']:
                tags = []
                if result['strict_result']:
                    tags.append("B2严格")
                if result['loose_result']:
                    tags.append("B2宽松")
                print(f"  [B2] [{i}/{total}] {result['stock']['code']} {result['stock']['name']} → {', '.join(tags)}")

    # 统计
    strict_count = sum(1 for r in all_results if r['strict_result'])
    loose_count = sum(1 for r in all_results if r['loose_result'])
    print(f"\nB2 筛选完成: 严格版 {strict_count} 只, 宽松版 {loose_count} 只")

    return all_results
