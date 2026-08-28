import argparse
import sys
import concurrent.futures
import datetime
import signal
# 导入API模块和模拟数据模块
from api import get_stock_list, get_stock_history_data
from mock_data import get_mock_stock_list, get_mock_stock_history_data
from filter import b1_strategy_filter, ultra_short_strategy_filter
from config import CONCURRENCY_CONFIG, STORAGE_CONFIG, B1_STRATEGY_CONFIG
from retry_manager import add_failed_stock, get_failed_stocks, remove_failed_stock

# 全局变量，用于控制退出
should_exit = False

# 第一阶段市值快筛的实时数据缓存（供 process_stock 复用，避免重复调用）
_realtime_cache = {}

def signal_handler(sig, frame):
    """
    处理Ctrl+C信号
    """
    global should_exit
    print("\n正在停止处理...请稍候")
    should_exit = True

# 注册信号处理（仅在主线程中有效）
import threading
if threading.current_thread() is threading.main_thread():
    signal.signal(signal.SIGINT, signal_handler)

def _needs_fetch(stock_code: str) -> bool:
    """
    检查该股票是否需要从API拉取数据（任意一个文件过期/不存在则需要拉取）
    """
    from data_storage import load_stock_data, get_data_file_path
    import os
    # B1策略需要的三个文件：日K、周K、实时
    for key, period in [
        (stock_code, 'd'),
        (stock_code, 'w'),
        (f"{stock_code}_realtime", 'd'),
    ]:
        path = get_data_file_path(key, period)
        if not os.path.exists(path):
            return True
        # 复用 load_stock_data 的过期判断（返回 None 说明过期）
        data = load_stock_data(key, period)
        if data is None:
            return True
    return False



def process_stock(stock, strategy='b1', mock=False, retry=False):
    """
    处理单个股票的筛选
    """
    global should_exit
    if should_exit:
        return {
            'stock': stock,
            'status': 'cancelled',
            'message': '处理被取消',
            'result': False,
            'details': {}
        }
    
    try:
        # 获取股票历史数据
        if mock:
            history_data = get_mock_stock_history_data(stock['code'], period='d', limit=200)
        else:
            # 尝试获取数据，最多重试3次
            retry_count = 0
            max_retries = 3
            while retry_count < max_retries:
                # 在retry模式下，强制不使用本地数据
                use_local = not retry and STORAGE_CONFIG['use_local_data']
                history_data = get_stock_history_data(stock['code'], period='d', limit=200, use_local=use_local)
                if history_data:
                    break
                retry_count += 1
                print(f"获取股票 {stock['code']} 数据失败，正在重试 ({retry_count}/{max_retries})...")
                import time
                time.sleep(1)  # 等待1秒后重试
        
        if not history_data:
            error_message = '无法获取历史数据'
            add_failed_stock(stock, error_message)
            return {
                'stock': stock,
                'status': 'error',
                'message': error_message,
                'result': False,
                'details': {}
            }
        
        # 提取详细数据
        details = {}
        if history_data:
            # 提取最新的价格数据
            latest_data = history_data[-1]
            details = {
                'close': latest_data.get('c', 0),
                'high': latest_data.get('h', 0),
                'low': latest_data.get('l', 0),
                'open': latest_data.get('o', 0),
                'volume': latest_data.get('v', 0),
                'amount': latest_data.get('a', 0),
                # 中文字段，与 indicators 中的收盘价保持一致
                '收盘价': latest_data.get('c', 0),
                '开盘价': latest_data.get('o', 0),
                '最高价': latest_data.get('h', 0),
                '最低价': latest_data.get('l', 0),
            }
        
        # 应用筛选策略
        result = False
        if strategy == 'b1':
            # 获取周K数据
            if mock:
                weekly_history_data = get_mock_stock_history_data(stock['code'], period='w', limit=100)
            else:
                # 在retry模式下，强制不使用本地数据
                use_local = not retry and STORAGE_CONFIG['use_local_data']
                weekly_history_data = get_stock_history_data(stock['code'], period='w', limit=100, use_local=use_local)
            
            # 获取实时数据（优先从第一阶段市值快筛的缓存中获取，避免重复调用）
            realtime_data = None
            if not mock:
                realtime_data = _realtime_cache.get(stock['code'])
                if realtime_data is None:
                    from api import get_stock_realtime_data
                    realtime_data = get_stock_realtime_data(stock['code'])
            
            filter_result = b1_strategy_filter(history_data, weekly_history_data, realtime_data)
            if isinstance(filter_result, dict):
                result = filter_result.get('result', False)  # 这里是原始B1结果，决定是否"符合条件"
                # 将筛选条件和指标添加到详细数据中
                details.update(filter_result.get('conditions', {}))
                details.update(filter_result.get('kdj', {}))
                details.update(filter_result.get('indicators', {}))
                
                # 添加新增条件的单独结果
                details['新增条件1_30日内倍量'] = filter_result.get('new_condition_1', False)
                details['新增条件2_120日内无大量卖出'] = filter_result.get('new_condition_2', False)
                details['新增条件3_30日内涨幅控制'] = filter_result.get('new_condition_3', False)
                details['新增条件4_30日内换手率控制'] = filter_result.get('new_condition_4', False)
                
                # 添加评分相关数据
                details['新增条件总分'] = filter_result.get('new_conditions_score', 0)
                details['原始B1满足'] = filter_result.get('original_b1_result', False)
                
                # 添加6个新增统计项
                details['统计_日K3天斜率<0.2'] = filter_result.get('stat_slope_3d_lt_02', False)
                details['统计_黄白gap>5%'] = filter_result.get('stat_gap_gt_5pct', False)
                details['统计_斜率三条件'] = filter_result.get('stat_slope_triple', False)
                details['统计_30天无连续涨停'] = filter_result.get('stat_no_consecutive_limit_up', True)
                details['统计_无长上影'] = filter_result.get('stat_no_long_upper_shadow', True)
                details['统计_30天涨幅达标'] = filter_result.get('stat_30d_change_within_limit', None)
                
                # 计算5天回测收益（对所有股票，不仅仅是符合B1条件的）
                from filter import calculate_backtest_return
                backtest_result = calculate_backtest_return(history_data, len(history_data) - 1)
                if backtest_result:
                    details['5天回测收益率'] = backtest_result.get('return_rate', 0)
                    details['5天前价格'] = backtest_result.get('start_price', 0)
                else:
                    details['5天回测收益率'] = 0
                    details['5天前价格'] = 0
            else:
                # 如果filter_result是False，说明数据不足，填充默认值
                error_message = '数据不足，无法完成筛选'
                return {
                    'stock': stock,
                    'status': 'error',
                    'message': error_message,
                    'result': False,
                    'details': details
                }
        else:
            filter_result = ultra_short_strategy_filter(history_data)
            if isinstance(filter_result, dict):
                result = filter_result.get('result', False)
                # 将筛选条件和指标添加到详细数据中
                details.update(filter_result.get('conditions', {}))
                details.update(filter_result.get('indicators', {}))
        
        # 处理成功后不再从失败列表中移除，因为失败列表在启动时已经清空
        
        return {
            'stock': stock,
            'status': 'success',
            'message': '处理成功',
            'result': result,
            'details': details
        }
    except Exception as e:
        error_message = f"处理失败: {str(e)}"
        print(f"处理股票 {stock['code']} 时发生错误: {error_message}")
        add_failed_stock(stock, error_message)
        return {
            'stock': stock,
            'status': 'error',
            'message': error_message,
            'result': False,
            'details': {}
        }


def run_filter(strategy='b1', test=False, mock=False, retry=False, debug=False):
    """
    核心筛选逻辑，返回结构化的筛选结果列表。

    Args:
        strategy: 筛选策略，'b1' 或 'ultra_short'
        test: 测试模式，只使用10个股票
        mock: 使用模拟数据
        retry: 只处理失败列表中的股票
        debug: 调试模式，不更新数据（跳过市值快筛和API拉取），只用本地缓存

    Returns:
        List[dict]: 筛选结果列表，每个元素包含 stock、status、message、result、details 字段
    """
    global should_exit

    # 脚本启动前删除历史失败的股票数据
    if not retry:
        from retry_manager import clear_failed_stocks
        print("删除历史失败的股票数据...")
        clear_failed_stocks()

    print("开始股票筛选...")
    print(f"使用策略：{'B1波段' if strategy == 'b1' else '超短线游击战法'}")

    # 获取股票列表
    print("获取股票列表中...")
    if retry:
        print("只处理失败列表中的股票")
        failed_stocks = get_failed_stocks()
        stock_list = []
        for item in failed_stocks:
            stock_list.append({
                'code': item['code'],
                'name': item['name'],
                'exchange': item['exchange']
            })
    elif mock:
        print("使用模拟数据")
        stock_list = get_mock_stock_list()
    else:
        print("使用真实API数据")
        stock_list = get_stock_list()

    if not stock_list:
        print("无法获取股票列表")
        return []

    # 剔除创业板股票（代码以300、301、302开头的）、科创板股票（688开头）、ST股票和退市股票
    filtered_stock_list = []
    for stock in stock_list:
        code = stock['code'].split('.')[0]
        name = stock['name']
        if (code.startswith('300') or code.startswith('301') or code.startswith('302') or code.startswith('688')):
            continue
        if name.startswith('ST') or name.startswith('*ST'):
            continue
        if '退市' in name:
            continue
        filtered_stock_list.append(stock)

    print(f"剔除创业板、科创板、ST、退市股票后，剩余 {len(filtered_stock_list)} 只股票")
    stock_list = filtered_stock_list

    # ── Debug 模式：强制使用本地缓存，不调用任何 API ──
    if debug:
        print("🔧 调试模式：跳过市值快筛和数据更新，强制使用本地缓存")
        # 临时将缓存有效期设为极大值，使所有本地数据都被视为有效
        STORAGE_CONFIG['daily_kline_max_age_hours'] = 99999
        STORAGE_CONFIG['weekly_kline_max_age_hours'] = 99999
        STORAGE_CONFIG['realtime_data_max_age_hours'] = 99999
        STORAGE_CONFIG['max_data_age_hours'] = 99999

    # ── 第一阶段：快速排除（市值 + 涨幅预判）──
    # 拉实时行情，用市值和涨幅条件提前排除不可能通过任何策略的股票
    # B1硬条件：流通市值≥80亿 且 总市值≥100亿
    # B2硬条件：当日涨幅≥3.95%
    # 逻辑：只要可能满足B1或B2其中之一就保留，都不满足则排除
    realtime_cache = {}  # 缓存实时数据，第二阶段复用（避免重复调用）
    if not mock and not test and not retry and not debug:
        print("第一阶段：快速排除（市值+涨幅预判）...")
        from api import get_stock_realtime_data
        min_lt = B1_STRATEGY_CONFIG['min_circulating_market_cap'] * 10000  # 万元→元
        min_sz = B1_STRATEGY_CONFIG['min_total_market_cap'] * 10000

        quick_passed = []
        excluded_no_b1_no_b2 = 0
        for i, stock in enumerate(stock_list):
            if should_exit:
                break
            realtime = get_stock_realtime_data(stock['code'])
            if realtime:
                realtime_cache[stock['code']] = realtime
                lt = realtime.get('lt', 0) or 0
                sz = realtime.get('sz', 0) or 0
                pct_change = realtime.get('pc', 0) or 0  # 涨跌幅%

                # B1候选：市值达标
                b1_candidate = (lt >= min_lt and sz >= min_sz)
                # B2候选：涨幅≥3.95%（B2严格/宽松的硬条件）
                b2_candidate = (pct_change >= 3.95)

                if b1_candidate or b2_candidate:
                    quick_passed.append(stock)
                else:
                    excluded_no_b1_no_b2 += 1
            else:
                # 获取失败，保留（不误杀）
                quick_passed.append(stock)

            if (i + 1) % 500 == 0:
                print(f"  快速排除进度: {i+1}/{len(stock_list)}")

        print(f"快速排除完成：{len(stock_list)} → {len(quick_passed)} 只（排除 {excluded_no_b1_no_b2} 只：市值不达标且涨幅<3.95%）")
        stock_list = quick_passed

    # 将缓存写入模块级变量，供 process_stock 复用
    global _realtime_cache
    _realtime_cache = realtime_cache

    # 测试模式下只使用10个股票
    if test:
        test_stocks = stock_list[:10]
        print(f"测试模式：使用前10个股票进行测试")
        stock_list = test_stocks

    print(f"共获取到 {len(stock_list)} 只股票")
    print("开始筛选...")

    # 筛选结果
    filtered_stocks = []
    total_stocks = len(stock_list)

    # 预检查：分成本地有效 vs 需要拉取两组
    if debug:
        # debug 模式：全部视为本地有效，不拉取任何数据
        print("🔧 调试模式：跳过预检查，全部使用本地缓存")
        local_stocks = stock_list
        fetch_stocks = []
    elif not mock and not retry and STORAGE_CONFIG['use_local_data']:
        print("预检查本地缓存...")
        local_stocks = []
        fetch_stocks = []
        for s in stock_list:
            if _needs_fetch(s['code']):
                fetch_stocks.append(s)
            else:
                local_stocks.append(s)
        print(f"本地有效：{len(local_stocks)} 只（5线程）  需拉取：{len(fetch_stocks)} 只（2线程）")
    else:
        local_stocks = []
        fetch_stocks = stock_list

    all_results = []
    processed_count = 0

    def _run_batch(batch, workers):
        nonlocal processed_count
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_stock = {executor.submit(process_stock, s, strategy, mock, retry): s for s in batch}
            for future in concurrent.futures.as_completed(future_to_stock):
                if should_exit:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                s = future_to_stock[future]
                processed_count += 1
                try:
                    result = future.result()
                    all_results.append(result)
                    if result['result']:
                        filtered_stocks.append(result['stock'])
                    status = "符合条件" if result['result'] else "不符合条件"
                    if result['status'] == 'error':
                        status = f"错误: {result['message']}"
                    print(f"正在处理 [{processed_count}/{total_stocks}] [{s['code']}] [{s['name']}] [{status}]")
                except Exception as exc:
                    print(f"处理股票 {s['code']} 时发生错误: {exc}")

    # 本地有效的：5线程并行
    if local_stocks:
        print(f"处理本地缓存股票（5线程）...")
        _run_batch(local_stocks, 5)

    # 需要拉取的：2线程（避免被ban）
    if fetch_stocks and not should_exit:
        print(f"处理需拉取股票（2线程）...")
        _run_batch(fetch_stocks, 2)

    if should_exit:
        print("处理已取消")
        return all_results

    # 对B1策略的结果进行特殊排序
    if strategy == 'b1':
        # 过滤出符合条件的结果
        qualified_results = [r for r in all_results if r['result'] and r['status'] == 'success']

        # 按新增条件总分降序排序，然后按到黄线距离升序排序
        qualified_results.sort(key=lambda x: (
            -x['details'].get('新增条件总分', 0),  # 总分越高越好（降序）
            x['details'].get('到黄线距离', float('inf'))  # 距离越小越好（升序）
        ))

        # 更新all_results，使符合条件的股票排在前面
        other_results = [r for r in all_results if not (r['result'] and r['status'] == 'success')]
        all_results = qualified_results + other_results
    else:
        # 对超短线策略按原来的逻辑排序
        qualified_results = [r for r in all_results if r['result'] and r['status'] == 'success']
        qualified_results.sort(key=lambda x: x['details'].get('到黄线距离', float('inf')))
        other_results = [r for r in all_results if not (r['result'] and r['status'] == 'success')]
        all_results = qualified_results + other_results

    return all_results


def main():
    """
    主函数（命令行入口）
    """
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='股票筛选工具')
    parser.add_argument('--strategy', type=str, choices=['b1', 'ultra_short'], default='b1',
                        help='筛选策略：b1（B1波段）或 ultra_short（超短线游击战法）')
    parser.add_argument('--test', action='store_true',
                        help='测试模式，只使用10个股票进行测试')
    parser.add_argument('--output', type=str, default='file',
                        help='输出方式：screen（屏幕）或 file（文件）。默认值为file，会生成带时间戳的CSV文件')
    parser.add_argument('--mock', action='store_true',
                        help='使用模拟数据进行测试，避免API调用限制')
    parser.add_argument('--retry', action='store_true',
                        help='只处理失败列表中的股票，系统会自动记录API调用失败的股票到failed_stocks.json文件。在retry模式下，会强制重新拉取数据，不使用本地数据')
    args = parser.parse_args()

    # 调用核心筛选逻辑
    all_results = run_filter(
        strategy=args.strategy,
        test=args.test,
        mock=args.mock,
        retry=args.retry
    )

    if not all_results:
        print("无法获取股票列表，程序退出")
        sys.exit(1)

    # 输出筛选结果
    total_stocks = len(all_results)
    filtered_stocks = [r for r in all_results if r['result'] and r['status'] == 'success']
    print("\n筛选完成！")
    print(f"共处理 {total_stocks} 只股票，筛选出 {len(filtered_stocks)} 只符合条件的股票")

    # 输出评分统计（B1策略）
    if args.strategy == 'b1':
        qualified_results = [r for r in all_results if r['result'] and r['status'] == 'success']
        if qualified_results:
            print(f"\n评分统计（符合条件的{len(qualified_results)}只股票）：")
            score_counts = {}
            for result in qualified_results:
                score = result['details'].get('新增条件总分', 0)
                score_counts[score] = score_counts.get(score, 0) + 1

            for score in sorted(score_counts.keys(), reverse=True):
                count = score_counts[score]
                print(f"  总分{score}分: {count}只股票")

    # 生成汇总表
    print("\n汇总表：")
    print("-" * 150)
    print(f"{'股票代码':<10} {'股票名称':<20} {'交易所':<10} {'状态':<10} {'结果':<10} {'详细数据':<60}")
    print("-" * 150)

    for result in all_results:
        stock = result['stock']
        status = "成功" if result['status'] == 'success' else "错误"
        result_str = "符合" if result['result'] else "不符合"
        details = result.get('details', {})
        details_str = str(details)
        print(f"{stock['code']:<10} {stock['name']:<20} {stock['exchange']:<10} {status:<10} {result_str:<10} {details_str:<60}")

    print("-" * 150)

    # 如果选择输出到文件
    if args.output == 'file':
        # 生成带时间戳的文件名
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"{args.strategy}_filtered_stocks_{timestamp}.csv"

        # ===== B1策略：固定列顺序，按逻辑分组 =====
        if args.strategy == 'b1':
            field_list = [
                # 【基本信息】
                '股票代码', '股票名称', '交易所', '状态', '结果', 'message',
                # 【价格与行情】
                '收盘价', '开盘价', '最高价', '最低价', '涨幅', '振幅',
                'close', 'open', 'high', 'low', 'volume', 'amount',
                # 【市值】
                '总市值', '流通市值',
                # 【B1原始条件 - 判断结果（11个）】
                'J<13', '收盘价>MA60', '收盘价>ZXDKX', 'ZXDQ>ZXDKX',
                '振幅<7', '涨幅>=-2', '涨幅<2',
                '倍量柱条件', '市值条件',
                'n-1日K在黄白值之间', 'n-1周K高于白线',
                '原始B1满足',
                # 【B1原始条件 - 指标值】
                'J', 'K', 'D',
                'MA60',
                '白线', '黄线', 'ZXDQ', 'ZXDKX',
                'n-1日收盘价', '到黄线距离',
                'n-1周收盘价', '周K白线',
                # 【新增4个评分条件 - 判断结果与统计值】
                '新增条件总分',
                '新增条件1_30日内倍量', '新增条件2_120日内无大量卖出',
                '新增条件3_30日内涨幅控制', '新增条件4_30日内换手率控制',
                '30日倍量次数',
                '120日最大成交量', '120日大量卖出次数',
                '30日连续2日涨幅违规次数', '30日连续3日涨幅违规次数',
                '30日单日换手率违规次数', '30日单周换手率违规次数',
                # 【5天回测】
                '5天回测收益率', '5天前价格',
                # 【附加统计项 - true/false】
                '日K3天斜率<0.2',
                '黄白gap>5%',
                '斜率三条件',
                '30天无连续涨停',
                '30日K无长上影', '120周K无长上影', '无长上影',
                '30天涨幅达标',
                # 【形态统计项 - true/false】
                '无顶部大风车', '无非正常放量', '无跳空',
                # 【附加统计项 - 数值】
                '日K3天斜率',
                '黄白gap占股价%',
                '30日K斜率', '120周K斜率',
                '30天涨幅', '30天涨幅限制',
                # 【统计项（stock_filter.py写入的冗余字段，保留兼容）】
                '统计_日K3天斜率<0.2', '统计_黄白gap>5%', '统计_斜率三条件',
                '统计_30天无连续涨停', '统计_无长上影', '统计_30天涨幅达标',
            ]
            # 收集实际存在但不在固定列表里的字段，追加到末尾
            all_fields = set(['股票代码', '股票名称', '交易所', '状态', '结果', 'message'])
            for result in all_results:
                all_fields.update(result.get('details', {}).keys())
            extra_fields = sorted(f for f in all_fields if f not in field_list)
            field_list = field_list + extra_fields
        else:
            # 非B1策略：收集所有字段，按字母排序
            all_fields = set(['股票代码', '股票名称', '交易所', '状态', '结果', 'message'])
            for result in all_results:
                all_fields.update(result.get('details', {}).keys())
            field_list = sorted(all_fields)

        with open(output_file, 'w', encoding='utf-8') as f:
            # 写入表头
            f.write(','.join(field_list) + '\n')

            # 写入数据
            for result in all_results:
                stock = result['stock']
                row_data = {
                    '股票代码': stock['code'],
                    '股票名称': stock['name'],
                    '交易所': stock['exchange'],
                    '状态': "成功" if result['status'] == 'success' else "错误",
                    '结果': "符合" if result['result'] else "不符合",
                    'message': result.get('message', '')
                }
                # 添加详细数据
                row_data.update(result.get('details', {}))

                # 构建行
                row = []
                for field in field_list:
                    value = row_data.get(field, '')
                    # 处理None值，替换为空字符串
                    if value is None:
                        value = ''
                    # 处理包含逗号的值
                    if isinstance(value, str) and ',' in value:
                        value = f'"{value}"'
                    row.append(str(value))

                f.write(','.join(row) + '\n')

        print(f"\n汇总结果已保存到 {output_file}")

if __name__ == "__main__":
    main()
