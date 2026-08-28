import numpy as np
from config import B1_STRATEGY_CONFIG, ULTRA_SHORT_STRATEGY_CONFIG

def calculate_backtest_return(stock_data, current_index, days=5):
    """
    计算回测收益率（回测过去5天）
    stock_data: 历史数据
    current_index: 当前数据在历史数据中的索引
    days: 回测天数
    """
    try:
        if current_index < days:
            return None
        
        # 获取5天前的价格和当前价格
        past_price = stock_data[current_index - days]['c']
        current_price = stock_data[current_index]['c']
        
        # 计算5天收益率
        return_rate = (current_price - past_price) / past_price * 100
        
        return {
            'days': days,
            'start_price': past_price,
            'end_price': current_price,
            'return_rate': return_rate
        }
    except Exception as e:
        print(f"计算回测收益失败: {str(e)}")
        return None

def calculate_rsv(close_prices, high_prices, low_prices, n=B1_STRATEGY_CONFIG['n']):
    """
    计算RSV值
    """
    if len(close_prices) < n:
        return None
    # 计算最近n天的最高价和最低价
    recent_high = max(high_prices[-n:])
    recent_low = min(low_prices[-n:])
    rng = recent_high - recent_low
    if rng == 0:
        return 50
    # 计算RSV值
    rsv = (close_prices[-1] - recent_low) / rng * 100
    return rsv

def calculate_kdj(rsv_values, k_prev=50, d_prev=50):
    """
    计算KDJ指标
    """
    if not rsv_values:
        return 50, 50, 50
    
    k_values = []
    d_values = []
    j_values = []
    
    # 使用第一个RSV值作为初始K值
    k = rsv_values[0]
    d = k
    
    k_values.append(k)
    d_values.append(d)
    j_values.append(3 * k - 2 * d)
    
    # 计算后续的KDJ值
    for rsv in rsv_values[1:]:
        k = (2/3) * k + (1/3) * rsv
        d = (2/3) * d + (1/3) * k
        j = 3 * k - 2 * d
        k_values.append(k)
        d_values.append(d)
        j_values.append(j)
    
    return k_values[-1], d_values[-1], j_values[-1]

def calculate_ema(prices, period):
    """
    计算指数移动平均线
    """
    if len(prices) < period:
        return None
    ema = []
    multiplier = 2 / (period + 1)
    # 第一个EMA值使用简单平均
    ema.append(sum(prices[:period]) / period)
    # 计算后续EMA值
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema

def calculate_ma(prices, period):
    """
    计算简单移动平均线
    """
    if len(prices) < period:
        return None
    ma = []
    for i in range(len(prices) - period + 1):
        ma.append(sum(prices[i:i+period]) / period)
    return ma

def b1_strategy_filter(stock_data, weekly_stock_data=None, realtime_data=None):
    """
    B1波段原始条件公式筛选（增强版，包含新的4个条件和评分机制）
    realtime_data: 实时数据字典，含 hs(换手率%), lt(流通市值元), sz(总市值元)
    """
    # 检查数据是否足够
    min_data_days = max(B1_STRATEGY_CONFIG['m4'], 120)  # 至少需要120天数据
    if len(stock_data) < min_data_days:
        print(f"数据不足：{len(stock_data)}条，需要至少{min_data_days}条")
        return False
    
    # 提取数据
    close_prices = [item['c'] for item in stock_data]
    high_prices = [item['h'] for item in stock_data]
    low_prices = [item['l'] for item in stock_data]
    volumes = [item['v'] for item in stock_data]
    
    # 计算KDJ
    rsv_values = []
    n = B1_STRATEGY_CONFIG['n']
    for i in range(n-1, len(close_prices)):
        rsv = calculate_rsv(close_prices[:i+1], high_prices[:i+1], low_prices[:i+1], n)
        if rsv is not None:
            rsv_values.append(rsv)
    
    if len(rsv_values) < 2:
        return False
    
    k, d, j = calculate_kdj(rsv_values)
    
    # 计算ZXDQ和ZXDKX
    ema_period = B1_STRATEGY_CONFIG['ema_period']
    ema10 = calculate_ema(close_prices, ema_period)
    if ema10 is None:
        return False
    zxdq = calculate_ema(ema10, ema_period)
    if zxdq is None:
        return False
    zxdq = zxdq[-1]
    
    # 计算白线：EMA(EMA(C,10),10)
    white_line = zxdq  # 因为zxdq就是EMA(EMA(C,10),10)
    
    m1 = B1_STRATEGY_CONFIG['m1']
    m2 = B1_STRATEGY_CONFIG['m2']
    m3 = B1_STRATEGY_CONFIG['m3']
    m4 = B1_STRATEGY_CONFIG['m4']
    ma14 = calculate_ma(close_prices, m1)
    ma28 = calculate_ma(close_prices, m2)
    ma57 = calculate_ma(close_prices, m3)
    ma114 = calculate_ma(close_prices, m4)
    
    if None in [ma14, ma28, ma57, ma114]:
        return False
    
    zxdkx = (ma14[-1] + ma28[-1] + ma57[-1] + ma114[-1]) / 4
    
    # 计算振幅和涨幅
    amplitude = 0
    change = 0
    if len(close_prices) > 1 and close_prices[-2] > 0:
        amplitude = (high_prices[-1] - low_prices[-1]) / close_prices[-2] * 100
        change = (close_prices[-1] - close_prices[-2]) / close_prices[-2] * 100
    
    # 计算MA60
    ma60_period = B1_STRATEGY_CONFIG['ma60_period']
    ma60 = calculate_ma(close_prices, ma60_period)
    if ma60 is None:
        return False
    ma60 = ma60[-1]
    
    # 倍量柱条件
    volume_condition = False
    volume_multiplier = B1_STRATEGY_CONFIG['volume_multiplier']
    volume_check_days = B1_STRATEGY_CONFIG['volume_check_days']
    for i in range(1, min(volume_check_days, len(volumes))):
        # 检查前一天成交量是否为0，避免除以零错误
        if volumes[-(i+1)] > 0 and volumes[-i] / volumes[-(i+1)] >= volume_multiplier:
            volume_condition = True
            break
    
    # 流通市值和总市值条件（从实时数据获取）
    # 单位：元，配置中是万元，需要转换
    min_lt = B1_STRATEGY_CONFIG['min_circulating_market_cap'] * 10000  # 万元转元
    min_sz = B1_STRATEGY_CONFIG['min_total_market_cap'] * 10000
    lt_value = 0  # 流通市值
    sz_value = 0  # 总市值
    market_cap_condition = True  # 默认满足（无实时数据时）
    if realtime_data:
        lt_value = realtime_data.get('lt', 0) or 0
        sz_value = realtime_data.get('sz', 0) or 0
        if lt_value > 0 and sz_value > 0:
            market_cap_condition = lt_value >= min_lt and sz_value >= min_sz
    
    # 综合条件
    j_threshold = B1_STRATEGY_CONFIG['j_threshold']
    amplitude_threshold = B1_STRATEGY_CONFIG['amplitude_threshold']
    change_min_threshold = B1_STRATEGY_CONFIG['change_min_threshold']
    change_max_threshold = B1_STRATEGY_CONFIG['change_max_threshold']
    
    # 获取n-1日的收盘价（前一天的收盘价）
    prev_close = close_prices[-2] if len(close_prices) > 1 else close_prices[-1]
    
    # 计算黄线（ZXDKX）和白线（ZXDQ）
    yellow_line = zxdkx
    
    # 检查n-1日K是否在黄白值之间
    between_yellow_white = min(yellow_line, white_line) <= prev_close <= max(yellow_line, white_line)
    
    # 计算n-1日K到黄线的距离
    distance_to_yellow = abs(prev_close - yellow_line)
    
    # 检查n-1周K是否高于白线
    weekly_above_white = True  # 默认值
    if weekly_stock_data and len(weekly_stock_data) >= 2:
        # 提取周K收盘价
        weekly_close_prices = [item['c'] for item in weekly_stock_data]
        # 计算周K的白线：EMA(EMA(C,10),10)
        weekly_ema10 = calculate_ema(weekly_close_prices, ema_period)
        if weekly_ema10:
            weekly_white_line = calculate_ema(weekly_ema10, ema_period)
            if weekly_white_line:
                # 获取n-1周的收盘价
                weekly_prev_close = weekly_close_prices[-2]
                weekly_white_line = weekly_white_line[-1]
                weekly_above_white = weekly_prev_close > weekly_white_line

    # ========== 新增的4个条件 ==========
    # 条件1：30交易日内至少1天成交量是前一日的2倍（越多越好）
    cond1_count = 0
    cond1_satisfied = False
    if len(volumes) >= 31:  # 需要至少31天数据来检查30天内的倍量
        for i in range(1, min(31, len(volumes))):
            if volumes[-(i+1)] > 0 and volumes[-i] / volumes[-(i+1)] >= 2:
                cond1_count += 1
        cond1_satisfied = cond1_count >= 1
    
    # 条件2：120交易日内无"放量阴线"（主力出货信号）
    # 放量阴线定义：收阴（收盘<开盘）且 成交量 > 近20日均量的中位数 * 2.5
    # 用中位数而非最大值作为基准，避免异常值干扰
    # 只有"放量+收阴"才算卖出信号，单纯放量（可能是买入）不算
    cond2_satisfied = True
    cond2_base_vol = 0
    cond2_violations = 0
    if len(stock_data) >= 120:
        check_data = stock_data[-120:]
        for i in range(20, len(check_data)):
            item = check_data[i]
            o_i = item['o']
            c_i = item['c']
            v_i = item['v']
            # 计算前20日成交量中位数作为基准
            prev_20_vols = sorted([check_data[j]['v'] for j in range(i - 20, i)])
            median_vol = prev_20_vols[10]  # 中位数（第11个）
            # 放量阴线：收阴 + 成交量 > 中位数 * 2.5
            if c_i < o_i and median_vol > 0 and v_i > median_vol * 2.5:
                cond2_violations += 1
        cond2_base_vol = median_vol if 'median_vol' in dir() else 0
        cond2_satisfied = cond2_violations == 0
    
    # 条件3：30交易日内连续上涨阶段，连续2日涨幅≤40%、连续3日涨幅≤50%
    cond3_satisfied = True
    rate_2day_violations = 0
    rate_3day_violations = 0
    if len(close_prices) >= 30:
        # 检查最近30天的数据
        for i in range(len(close_prices) - 30, len(close_prices)):
            # 连续2日涨幅：从i-2到i的涨幅
            if i >= 2 and close_prices[i-2] > 0:
                rate_2day = (close_prices[i] / close_prices[i-2] - 1) * 100
                if rate_2day > 40:
                    rate_2day_violations += 1
            
            # 连续3日涨幅：从i-3到i的涨幅
            if i >= 3 and close_prices[i-3] > 0:
                rate_3day = (close_prices[i] / close_prices[i-3] - 1) * 100
                if rate_3day > 50:
                    rate_3day_violations += 1
        
        cond3_satisfied = rate_2day_violations == 0 and rate_3day_violations == 0
    
    # 条件4：30交易日内单日换手率≤15%、单周换手率≤40%
    # 使用实时数据中的流通市值和当前价格，计算流通股本，再用历史成交量算每日换手率
    # 历史数据 v 单位是手（1手=100股），换手率 = v*100 / 流通股本 * 100%
    cond4_satisfied = True
    daily_turnover_violations = 0
    weekly_turnover_violations = 0

    if realtime_data:
        lt_rt = realtime_data.get('lt', 0) or 0
        p_rt = realtime_data.get('p', 0) or 0
        if lt_rt > 0 and p_rt > 0:
            circulating_shares = lt_rt / p_rt  # 流通股本（股）
            # 检查最近30天的单日换手率
            for i in range(len(volumes) - 30, len(volumes)):
                daily_hs = (volumes[i] * 100 / circulating_shares) * 100
                if daily_hs > 15:
                    daily_turnover_violations += 1
            # 检查最近30天的单周换手率（5日累计）
            for i in range(len(volumes) - 30, len(volumes)):
                if i >= 4:
                    week_vol = sum(volumes[i-4:i+1])
                    weekly_hs = (week_vol * 100 / circulating_shares) * 100
                    if weekly_hs > 40:
                        weekly_turnover_violations += 1
            cond4_satisfied = daily_turnover_violations == 0 and weekly_turnover_violations == 0
    
    # 计算新增条件的总分
    new_conditions_score = sum([
        1 if cond1_satisfied else 0,
        1 if cond2_satisfied else 0,
        1 if cond3_satisfied else 0,
        1 if cond4_satisfied else 0
    ])

    # ========== 新增6个统计项（不影响B1筛选结果，仅展示） ==========

    # 统计1：日K 3天内斜率 < 0.2
    # 斜率 = (最新收盘价 - 3天前收盘价) / (3天前收盘价 * 3)，用百分比表示
    stat1_slope_3d = None
    stat1_slope_lt_02 = False
    if len(close_prices) >= 4:
        slope_3d = (close_prices[-1] - close_prices[-4]) / (close_prices[-4] * 3) * 100
        stat1_slope_3d = slope_3d
        stat1_slope_lt_02 = slope_3d < 0.2

    # 统计2：黄白gap > 股价的5%
    stat2_gap_pct = None
    stat2_gap_gt_5pct = False
    if close_prices[-1] > 0:
        gap = abs(yellow_line - white_line)
        stat2_gap_pct = gap / close_prices[-1] * 100
        stat2_gap_gt_5pct = stat2_gap_pct > 5.0

    # 统计3：30日K斜率≤1 AND 120日周K斜率>0 AND 120日周K斜率<30日K斜率
    # 30日K斜率：(最新收盘价 - 30天前收盘价) / (30天前收盘价 * 30) * 100
    stat3_slope_30d = None
    stat3_slope_120w = None
    stat3_cond = False
    if len(close_prices) >= 31:
        stat3_slope_30d = (close_prices[-1] - close_prices[-31]) / (close_prices[-31] * 30) * 100
    if weekly_stock_data and len(weekly_stock_data) >= 2:
        weekly_close = [item['c'] for item in weekly_stock_data]
        n_weeks = len(weekly_close)
        # 用实际可用的周K数量计算斜率（最多120根，至少2根）
        ref_idx = min(120, n_weeks - 1)
        stat3_slope_120w = (weekly_close[-1] - weekly_close[-ref_idx - 1]) / (weekly_close[-ref_idx - 1] * ref_idx) * 100
    if stat3_slope_30d is not None and stat3_slope_120w is not None:
        stat3_cond = (stat3_slope_30d <= 1.0) and (stat3_slope_120w > 0) and (stat3_slope_120w < stat3_slope_30d)

    # 统计4：30天内不能有连续的两个涨停
    # 涨停判断：当日收盘价 >= 前收盘价 * 1.099（考虑精度误差）
    stat4_no_consecutive_limit_up = True
    stat4_consecutive_limit_up_found = False
    if len(stock_data) >= 30:
        recent_30 = stock_data[-30:]
        for i in range(1, len(recent_30)):
            prev_c = recent_30[i-1].get('pc', 0) or recent_30[i-1].get('c', 0)
            curr_c = recent_30[i]['c']
            curr_pc = recent_30[i].get('pc', 0) or (recent_30[i-1]['c'])
            # 判断当日是否涨停：收盘价 >= 前收盘价 * 1.099
            is_limit_up_today = curr_c >= curr_pc * 1.099 if curr_pc > 0 else False
            if i >= 2:
                prev_pc_for_prev = recent_30[i-2].get('pc', 0) or recent_30[i-2].get('c', 0)
                prev_c_val = recent_30[i-1]['c']
                is_limit_up_prev = prev_c_val >= prev_pc_for_prev * 1.099 if prev_pc_for_prev > 0 else False
                if is_limit_up_today and is_limit_up_prev:
                    stat4_consecutive_limit_up_found = True
                    break
        stat4_no_consecutive_limit_up = not stat4_consecutive_limit_up_found

    # 统计5：120周K或30日K都不能出现长上影
    # 长上影定义：上影线长度 > 实体长度 * 2，且上影线 > 当日振幅的30%
    # 额外约束：排除十字星（实体太小的K线），且上影线占股价比例需 > 2%
    def has_long_upper_shadow(candles):
        """检查K线序列中是否有长上影线
        判断标准（全部满足）：
        1. 实体 > 收盘价 * 0.5%（排除十字星，避免误判）
        2. 上影线 > 收盘价 * 2%（上影线有实际意义的长度）
        3. 上影线 > 实体 * 2
        4. 上影线 > 振幅 * 30%
        """
        for item in candles:
            o = item['o']
            h = item['h']
            l = item['l']
            c = item['c']
            if c <= 0:
                continue
            body = abs(c - o)
            upper_shadow = h - max(c, o)
            total_range = h - l
            # 排除十字星（实体太小）和微小上影线
            if body <= c * 0.005:
                continue
            if upper_shadow <= c * 0.02:
                continue
            if total_range > 0 and upper_shadow > body * 2 and upper_shadow > total_range * 0.3:
                return True
        return False

    stat5_30d_no_long_upper = True
    stat5_120w_no_long_upper = True
    stat5_no_long_upper = True
    if len(stock_data) >= 30:
        stat5_30d_no_long_upper = not has_long_upper_shadow(stock_data[-30:])
    if weekly_stock_data and len(weekly_stock_data) >= 2:
        # 只检查最近20根周K（约5个月），避免历史数据过多导致误判
        recent_weekly = weekly_stock_data[-20:] if len(weekly_stock_data) > 20 else weekly_stock_data
        stat5_120w_no_long_upper = not has_long_upper_shadow(recent_weekly)
    stat5_no_long_upper = stat5_30d_no_long_upper and stat5_120w_no_long_upper

    # 统计6：30天内涨幅限制（按总市值分档）
    # 总市值100~400亿：涨幅<15%；400(含)~1000亿：涨幅<10%；1000亿(含)以上：涨幅<6%
    # 涨幅 = (最新收盘价 - 30天前收盘价) / 30天前收盘价 * 100
    stat6_30d_change = None
    stat6_limit = None
    stat6_within_limit = None  # None表示无法判断（无市值数据或市值不在范围内）
    if len(close_prices) >= 31:
        stat6_30d_change = (close_prices[-1] - close_prices[-31]) / close_prices[-31] * 100
    sz_yi = sz_value / 1e8 if sz_value > 0 else 0  # 转换为亿元
    if stat6_30d_change is not None and sz_yi > 0:
        if 100 <= sz_yi < 400:
            stat6_limit = 15.0
            stat6_within_limit = stat6_30d_change < 15.0
        elif 400 <= sz_yi < 1000:
            stat6_limit = 10.0
            stat6_within_limit = stat6_30d_change < 10.0
        elif sz_yi >= 1000:
            stat6_limit = 6.0
            stat6_within_limit = stat6_30d_change < 6.0

    # ========== 新增3个形态统计项（不影响B1筛选结果，仅展示） ==========
    # 所有条件检查最近120天数据，True=无该形态（好），False=出现该形态（差）

    # 形态1：120日内无"顶部大风车"（阴量）
    # 触发条件（全部满足才算出现）：
    #   1. 当日最高价 >= 前30日最高价 * 90%（阶段高位）
    #   2. 上影线 > 实体 * 2（上影线 = 最高价 - max(开盘,收盘)；实体 = |开盘-收盘|）
    #   3. 当日成交量 > 近5日均量 * 1.5
    #   4. 当日为阴线（收盘 < 开盘）
    stat7_no_top_windmill = True
    check_start = max(0, len(stock_data) - 120)
    for i in range(check_start, len(stock_data)):
        o_i = stock_data[i]['o']
        h_i = stock_data[i]['h']
        l_i = stock_data[i]['l']
        c_i = stock_data[i]['c']
        v_i = stock_data[i]['v']
        # 子条件4：阴线
        if c_i >= o_i:
            continue
        # 子条件1：阶段高位（前30日最高价的90%）
        prev30_start = max(0, i - 30)
        if prev30_start >= i:
            continue
        prev30_high = max(stock_data[j]['h'] for j in range(prev30_start, i))
        if h_i < prev30_high * 0.9:
            continue
        # 子条件2：上影线 > 实体 * 2
        body = abs(c_i - o_i)
        upper_shadow = h_i - max(c_i, o_i)
        if body == 0 or upper_shadow <= body * 2:
            continue
        # 子条件3：当日成交量 > 近5日均量 * 1.5
        prev5_start = max(0, i - 5)
        if prev5_start >= i:
            continue
        avg5_vol = sum(stock_data[j]['v'] for j in range(prev5_start, i)) / (i - prev5_start)
        if v_i <= avg5_vol * 1.5:
            continue
        # 四个子条件全部满足，出现顶部大风车
        stat7_no_top_windmill = False
        break

    # 形态2：120日内无"非正常放量"（阴量）
    # 触发条件（全部满足才算出现）：
    #   1. 当日成交量 > 近20日均量 * 3（单日暴量）
    #   2. 次日成交量 < 当日成交量 * 50%（次日缩量）
    #   3. 当日为阴线（收盘 < 开盘）
    stat8_no_abnormal_volume = True
    for i in range(check_start, len(stock_data) - 1):  # -1 因为需要看次日
        o_i = stock_data[i]['o']
        c_i = stock_data[i]['c']
        v_i = stock_data[i]['v']
        v_next = stock_data[i + 1]['v']
        # 子条件3：阴线
        if c_i >= o_i:
            continue
        # 子条件1：当日成交量 > 近20日均量 * 3
        prev20_start = max(0, i - 20)
        if prev20_start >= i:
            continue
        avg20_vol = sum(stock_data[j]['v'] for j in range(prev20_start, i)) / (i - prev20_start)
        if v_i <= avg20_vol * 3:
            continue
        # 子条件2：次日成交量 < 当日 * 50%
        if v_next >= v_i * 0.5:
            continue
        # 三个子条件全部满足，出现非正常放量
        stat8_no_abnormal_volume = False
        break

    # 形态3：120日内无跳空价格区间
    # 向上跳空：当日开盘价 > 前一日最高价（当日整个价格区间在前日之上）
    # 向下跳空：当日最高价 < 前一日最低价（当日整个价格区间在前日之下）
    stat9_no_gap = True
    for i in range(check_start, len(stock_data)):
        if i == 0:
            continue
        o_i = stock_data[i]['o']
        h_i = stock_data[i]['h']
        h_prev = stock_data[i - 1]['h']
        l_prev = stock_data[i - 1]['l']
        if o_i > h_prev:  # 向上跳空：当日开盘价高于前日最高价
            stat9_no_gap = False
            break
        if h_i < l_prev:  # 向下跳空：当日最高价低于前日最低价（整个区间无重叠）
            stat9_no_gap = False
            break
    
    conditions = {
        'J<13': j < j_threshold,
        '收盘价>MA60': close_prices[-1] > ma60,
        '收盘价>ZXDKX': close_prices[-1] > zxdkx,
        'ZXDQ>ZXDKX': zxdq > zxdkx,
        '振幅<7': amplitude < amplitude_threshold,
        '涨幅>=-2': change >= change_min_threshold,
        '涨幅<2': change < change_max_threshold,
        '倍量柱条件': volume_condition,
        '市值条件': market_cap_condition,
        'n-1日K在黄白值之间': between_yellow_white,
        'n-1周K高于白线': weekly_above_white
    }
    
    # 检查是否满足原始B1条件（所有11个条件）
    original_b1_satisfied = all(conditions.values())
    
    # 计算KDJ值
    kdj_values = {'K': k, 'D': d, 'J': j}
    
    # 计算其他指标
    indicators = {
        'ZXDQ': zxdq,
        'ZXDKX': zxdkx,
        'MA60': ma60,
        '收盘价': close_prices[-1],
        '振幅': amplitude,
        '涨幅': change,
        '白线': white_line,
        '黄线': yellow_line,
        'n-1日收盘价': prev_close,
        '到黄线距离': distance_to_yellow,
        # 新增条件的统计指标（不是条件本身）
        '30日倍量次数': cond1_count,
        '120日放量阴线次数': cond2_violations,
        '30日连续2日涨幅违规次数': rate_2day_violations,
        '30日连续3日涨幅违规次数': rate_3day_violations,
        '30日单日换手率违规次数': daily_turnover_violations,
        '30日单周换手率违规次数': weekly_turnover_violations,
        '新增条件总分': new_conditions_score,
        '原始B1满足': original_b1_satisfied,
        # 实时数据字段
        '流通市值': lt_value,
        '总市值': sz_value,
        # ===== 6个新增统计项（仅展示，不影响筛选） =====
        '日K3天斜率': stat1_slope_3d,
        '日K3天斜率<0.2': stat1_slope_lt_02,
        '黄白gap占股价%': stat2_gap_pct,
        '黄白gap>5%': stat2_gap_gt_5pct,
        '30日K斜率': stat3_slope_30d,
        '120周K斜率': stat3_slope_120w,
        '斜率三条件': stat3_cond,
        '30天无连续涨停': stat4_no_consecutive_limit_up,
        '30日K无长上影': stat5_30d_no_long_upper,
        '120周K无长上影': stat5_120w_no_long_upper,
        '无长上影': stat5_no_long_upper,
        '30天涨幅': stat6_30d_change,
        '30天涨幅限制': stat6_limit,
        '30天涨幅达标': stat6_within_limit,
        # ===== 3个新增形态统计项（仅展示，不影响筛选） =====
        '无顶部大风车': stat7_no_top_windmill,
        '无非正常放量': stat8_no_abnormal_volume,
        '无跳空': stat9_no_gap,
    }
    
    # 添加周K相关指标
    if weekly_stock_data and len(weekly_stock_data) >= 2:
        weekly_close_prices = [item['c'] for item in weekly_stock_data]
        weekly_ema10 = calculate_ema(weekly_close_prices, ema_period)
        if weekly_ema10:
            weekly_white_line = calculate_ema(weekly_ema10, ema_period)
            if weekly_white_line:
                indicators['n-1周收盘价'] = weekly_close_prices[-2]
                indicators['周K白线'] = weekly_white_line[-1]
                indicators['n-1周K高于白线'] = weekly_above_white
    
    return {
        'result': original_b1_satisfied,  # 只看原始B1条件是否满足（这个决定是否"符合条件"）
        'original_b1_result': original_b1_satisfied,  # 原始B1条件是否满足
        'conditions': conditions,
        'kdj': kdj_values,
        'indicators': indicators,
        'new_conditions_score': new_conditions_score,
        # 新增条件的单独结果（不影响主要筛选结果）
        'new_condition_1': cond1_satisfied,
        'new_condition_2': cond2_satisfied,
        'new_condition_3': cond3_satisfied,
        'new_condition_4': cond4_satisfied,
        # 6个新增统计项
        'stat_slope_3d_lt_02': stat1_slope_lt_02,
        'stat_gap_gt_5pct': stat2_gap_gt_5pct,
        'stat_slope_triple': stat3_cond,
        'stat_no_consecutive_limit_up': stat4_no_consecutive_limit_up,
        'stat_no_long_upper_shadow': stat5_no_long_upper,
        'stat_30d_change_within_limit': stat6_within_limit,
        'stat_no_top_windmill': stat7_no_top_windmill,
        'stat_no_abnormal_volume': stat8_no_abnormal_volume,
        'stat_no_gap': stat9_no_gap,
    }

def ultra_short_strategy_filter(stock_data):
    """
    超短线游击战法筛选
    """
    # 提取数据
    close_prices = [item['c'] for item in stock_data]
    open_prices = [item['o'] for item in stock_data]
    high_prices = [item['h'] for item in stock_data]
    low_prices = [item['l'] for item in stock_data]
    volumes = [item['v'] for item in stock_data]
    
    # 计算白线：EMA(EMA(C,10),10)
    ema_period = 10
    ema10 = calculate_ema(close_prices, ema_period)
    white_line = 0
    if ema10:
        zxdq = calculate_ema(ema10, ema_period)
        if zxdq:
            white_line = zxdq[-1]
    
    # 计算黄线：ZXDKX (MA14 + MA28 + MA57 + MA114) / 4
    m1 = 14
    m2 = 28
    m3 = 57
    m4 = 114
    ma14 = calculate_ma(close_prices, m1)
    ma28 = calculate_ma(close_prices, m2)
    ma57 = calculate_ma(close_prices, m3)
    ma114 = calculate_ma(close_prices, m4)
    yellow_line = 0
    if None not in [ma14, ma28, ma57, ma114]:
        yellow_line = (ma14[-1] + ma28[-1] + ma57[-1] + ma114[-1]) / 4
    
    # 计算砖型图
    var1a = []
    var3a = []
    brick_hhv_period = ULTRA_SHORT_STRATEGY_CONFIG['brick_hhv_period']
    brick_llv_period = ULTRA_SHORT_STRATEGY_CONFIG['brick_llv_period']
    for i in range(brick_hhv_period-1, len(close_prices)):
        hhv4 = max(high_prices[i-brick_hhv_period+1:i+1])
        llv4 = min(low_prices[i-brick_llv_period+1:i+1])
        # 避免除零错误
        if hhv4 - llv4 == 0:
            var1a_val = 0  # 默认值
            var3a_val = 50  # 默认值
        else:
            var1a_val = (hhv4 - close_prices[i]) / (hhv4 - llv4) * 100 - 90
            var3a_val = (close_prices[i] - llv4) / (hhv4 - llv4) * 100
        var1a.append(var1a_val)
        var3a.append(var3a_val)
    
    var1a_sma_period = ULTRA_SHORT_STRATEGY_CONFIG['var1a_sma_period']
    var3a_sma_period = ULTRA_SHORT_STRATEGY_CONFIG['var3a_sma_period']
    var2a = []
    var4a = []
    var5a = []
    brick = []
    
    if len(var1a) >= var1a_sma_period and len(var3a) >= var3a_sma_period:
        # 计算VAR2A
        for i in range(var1a_sma_period-1, len(var1a)):
            var2a_val = sum(var1a[i-var1a_sma_period+1:i+1]) / var1a_sma_period + 100
            var2a.append(var2a_val)
        
        # 计算VAR4A
        var4a_sma_period = ULTRA_SHORT_STRATEGY_CONFIG['var4a_sma_period']
        for i in range(var4a_sma_period-1, len(var3a)):
            var4a_val = sum(var3a[i-var4a_sma_period+1:i+1]) / var4a_sma_period
            var4a.append(var4a_val)
        
        # 计算VAR5A
        for i in range(var4a_sma_period-1, len(var4a)):
            var5a_val = sum(var4a[i-var4a_sma_period+1:i+1]) / var4a_sma_period + 100
            var5a.append(var5a_val)
        
        # 计算VAR6A和砖型图
        brick_threshold = ULTRA_SHORT_STRATEGY_CONFIG['brick_threshold']
        for i in range(len(var5a)):
            if i < len(var2a):
                var6a = var5a[i] - var2a[i]
                brick_val = var6a - brick_threshold if var6a > brick_threshold else 0
                brick.append(brick_val)
    
    # 当日绿转红条件
    yesterday_green = False
    today_red = False
    green_to_red = False
    yesterday_green_height = 0
    today_red_height = 0
    red_qualified = False
    
    if len(brick) >= 3:
        yesterday_green = brick[-2] < brick[-3]
        today_red = brick[-1] > brick[-2]
        green_to_red = yesterday_green and today_red
        
        # 红柱达标条件
        yesterday_green_height = abs(brick[-3] - brick[-2])
        today_red_height = abs(brick[-1] - brick[-2])
        red_height_ratio = ULTRA_SHORT_STRATEGY_CONFIG['red_height_ratio']
        red_qualified = today_red_height >= (yesterday_green_height * red_height_ratio) and yesterday_green_height > 0 and today_red_height > 0
    
    # 均线条件
    ma20_period = ULTRA_SHORT_STRATEGY_CONFIG['ma20_period']
    ma60_period = ULTRA_SHORT_STRATEGY_CONFIG['ma60_period']
    ma120_period = ULTRA_SHORT_STRATEGY_CONFIG['ma120_period']
    ma20 = calculate_ma(close_prices, ma20_period)
    ma60 = calculate_ma(close_prices, ma60_period)
    ma120 = calculate_ma(close_prices, ma120_period)
    ma_bullish = False
    
    if None not in [ma20, ma60, ma120]:
        ma_bullish = ma20[-1] > ma60[-1] and ma60[-1] > ma120[-1]
    
    # 量能条件
    volume_condition = True
    volume_check_days = ULTRA_SHORT_STRATEGY_CONFIG['volume_check_days']
    if len(close_prices) > volume_check_days:
        for i in range(1, min(volume_check_days+1, len(close_prices))):
            is_阴线日 = close_prices[-i] < open_prices[-i]
            if is_阴线日:
                if volumes[-i] >= volumes[-(i+1)]:
                    volume_condition = False
                    break
    
    # 检查条件：日K要高于白线或者黄线，且白线在黄线之上，价格不低于黄线
    day_k_above_line = True  # 默认值
    white_above_yellow = True  # 默认值
    price_not_below_yellow = True  # 默认值
    
    if white_line and yellow_line:
        # 获取最新的收盘价（日K）
        latest_close = close_prices[-1]
        # 日K要高于白线或者黄线
        day_k_above_line = latest_close > white_line or latest_close > yellow_line
        # 白线在黄线之上
        white_above_yellow = white_line > yellow_line
        # 价格不低于黄线
        price_not_below_yellow = latest_close >= yellow_line
    
    # 综合条件
    conditions = {
        '当日绿转红': green_to_red,
        '红柱达标': red_qualified,
        '均线多头': ma_bullish,
        '量能条件': volume_condition,
        '日K高于白线或黄线': day_k_above_line,
        '白线在黄线之上': white_above_yellow,
        '价格不低于黄线': price_not_below_yellow
    }
    
    # 计算红柱高度和绿柱高度的比值
    red_green_ratio = 0
    if yesterday_green_height > 0:
        red_green_ratio = today_red_height / yesterday_green_height
    
    # 计算其他指标
    indicators = {
        '白线': white_line,
        '黄线': yellow_line,
        '收盘价': close_prices[-1] if close_prices else 0,
        '日K高于白线或黄线': day_k_above_line,
        '白线在黄线之上': white_above_yellow,
        '价格不低于黄线': price_not_below_yellow,
        'MA20': ma20[-1] if ma20 else 0,
        'MA60': ma60[-1] if ma60 else 0,
        'MA120': ma120[-1] if ma120 else 0,
        '开盘价': open_prices[-1] if open_prices else 0,
        '最高价': high_prices[-1] if high_prices else 0,
        '最低价': low_prices[-1] if low_prices else 0,
        '成交量': volumes[-1] if volumes else 0,
        '砖型图值1': brick[-3] if len(brick) >= 3 else 0,
        '砖型图值2': brick[-2] if len(brick) >= 3 else 0,
        '砖型图值3': brick[-1] if len(brick) >= 3 else 0,
        '绿柱高度': yesterday_green_height,
        '红柱高度': today_red_height,
        '红柱绿柱比值': red_green_ratio
    }
    
    # 计算KDJ指标（与B1策略保持一致）
    n = B1_STRATEGY_CONFIG['n']
    rsv_values = []
    for i in range(n-1, len(close_prices)):
        rsv = calculate_rsv(close_prices[:i+1], high_prices[:i+1], low_prices[:i+1], n)
        if rsv is not None:
            rsv_values.append(rsv)
    
    k = d = j = 0
    if len(rsv_values) >= 2:
        k, d, j = calculate_kdj(rsv_values)
    
    # 添加KDJ指标
    indicators['K'] = k
    indicators['D'] = d
    indicators['J'] = j
    
    # 计算振幅和涨幅
    amplitude = 0
    change = 0
    if len(close_prices) > 1 and close_prices[-2] > 0:
        amplitude = (high_prices[-1] - low_prices[-1]) / close_prices[-2] * 100
        change = (close_prices[-1] - close_prices[-2]) / close_prices[-2] * 100
    
    indicators['振幅'] = amplitude
    indicators['涨幅'] = change
    
    # 添加ZXDQ和ZXDKX（与B1策略保持一致）
    zxdq = white_line  # 因为white_line就是EMA(EMA(C,10),10)
    zxdkx = yellow_line  # 因为yellow_line就是ZXDKX
    indicators['ZXDQ'] = zxdq
    indicators['ZXDKX'] = zxdkx
    
    # 流通市值和总市值条件（这里使用默认值，实际应该从API获取）
    market_cap_condition = True  # 假设满足条件
    conditions['市值条件'] = market_cap_condition
    
    return {
        'result': green_to_red and red_qualified and ma_bullish and volume_condition and day_k_above_line and white_above_yellow and price_not_below_yellow,
        'conditions': conditions,
        'indicators': indicators
    }
