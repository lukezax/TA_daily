# 配置文件

# B1波段策略参数
B1_STRATEGY_CONFIG = {
    # KDJ参数
    'n': 9,  # KDJ计算周期
    'm1': 14,  # ZXDKX计算周期1
    'm2': 28,  # ZXDKX计算周期2
    'm3': 57,  # ZXDKX计算周期3
    'm4': 114,  # ZXDKX计算周期4
    
    # EMA参数
    'ema_period': 10,  # ZXDQ计算周期
    
    # MA参数
    'ma60_period': 60,  # MA60计算周期
    
    # 筛选条件参数
    'j_threshold': 13,  # J值阈值
    'amplitude_threshold': 7,  # 振幅阈值(%)
    'change_min_threshold': -2,  # 涨幅最小值(%)
    'change_max_threshold': 2,  # 涨幅最大值(%)
    'volume_multiplier': 2,  # 倍量柱倍数
    'volume_check_days': 250,  # 倍量柱检查天数
    
    # 市值条件（单位：万元）
    'min_circulating_market_cap': 800000,  # 最小流通市值
    'min_total_market_cap': 1000000,  # 最小总市值
}

# 超短线游击战法参数
ULTRA_SHORT_STRATEGY_CONFIG = {
    # 砖型图参数
    'brick_hhv_period': 4,  # 最高价周期
    'brick_llv_period': 4,  # 最低价周期
    'var1a_sma_period': 4,  # VAR1A的SMA周期
    'var3a_sma_period': 6,  # VAR3A的SMA周期
    'var4a_sma_period': 6,  # VAR4A的SMA周期
    'brick_threshold': 4,  # 砖型图阈值
    
    # 红柱达标参数
    'red_height_ratio': 1.5,  # 红柱高度与绿柱高度的比例
    
    # 均线参数
    'ma20_period': 20,  # 20日均线周期
    'ma60_period': 60,  # 60日均线周期
    'ma120_period': 120,  # 120日均线周期
    
    # 量能条件参数
    'volume_check_days': 10,  # 量能检查天数
}

# API参数
API_CONFIG = {
    'token': '44FE41B5-3D9B-44FB-800B-12814D1202B2',  # 付费 token（兜底）
    'base_url': 'https://api.zhituapi.com',  # API基础URL
    'request_interval': 0.5,  # 请求间隔（秒）
    # 免费 token 列表（每天 200 次/token），优先使用
    'free_tokens': [
        '74DCAD17-3EC8-45D7-857D-A747D9CF5FDD',
        '559603A5-7824-4626-9BEC-2DDDC520DAD4',
        '7DF40DE4-14E7-45B9-BFBB-8543D32FCFC1',
        'B4E0D8B4-A247-4585-8321-ACCF1F038BD4',
    ],
    'free_token_daily_limit': 198,  # 每个免费 token 每天最多请求次数（留 2 次余量）
}

# 测试参数
TEST_CONFIG = {
    'mock_stock_count': 10,  # 模拟股票数量
    'mock_data_days': 150,  # 模拟数据天数
}

# 数据存储配置
STORAGE_CONFIG = {
    'use_local_data': True,  # 是否使用本地数据
    'max_data_age_hours': 24,  # 本地数据最大允许年龄（小时）- 日K线默认
    'daily_kline_max_age_hours': 24,  # 日K线缓存：24小时
    'weekly_kline_max_age_hours': 72,  # 周K线缓存：72小时（约3天，正常周会在周日晚和周三晚自动刷新）
    'realtime_data_max_age_hours': 1,  # 实时数据：1小时
    'stock_list_cache': False,  # 股票列表不缓存，每次重新拉取
}

# 并发配置
CONCURRENCY_CONFIG = {
    'max_workers': 2,  # 并发处理的最大工作线程数
}

# 时间范围配置
TIME_RANGE_CONFIG = {
    'days': 1300,  # 历史数据获取天数，需要足够长以支持：120周K（约840天）+ 条件2基准期（240天日K）
    'start_date': None,  # 开始日期（None表示自动计算），格式：YYYYMMDD
    'end_date': None,  # 结束日期（None表示自动计算），格式：YYYYMMDD
    'description': '历史数据时间范围配置，用于API调用获取股票历史数据',
    'reasoning': '设置为1300天：支持120周K斜率计算（约840天）、评分条件2的双窗口基准（240天日K）、以及所有技术指标（MA120等）',
}
