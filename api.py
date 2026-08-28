import requests
import time
import urllib3
from datetime import date
from config import API_CONFIG
from data_storage import load_stock_data, save_stock_data

# 智兔 API 后端部分服务器 SSL 证书域名不匹配，禁用验证避免间歇性 SSLError
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# API配置
BASE_URL = API_CONFIG['base_url']
REQUEST_INTERVAL = API_CONFIG['request_interval']

# Token 轮换管理
_token_usage = {}  # {token: count}
_usage_date = ""
_DAILY_LIMIT = API_CONFIG.get('free_token_daily_limit', 198)
_free_token_exhausted_printed = False  # 只打印一次切换提示


def _get_current_token():
    """获取当前可用的 token（优先免费 ，用完后切换到付费 token）"""
    global _token_usage, _usage_date, _free_token_exhausted_printed

    today = date.today().isoformat()
    if _usage_date != today:
        _token_usage = {}
        _usage_date = today
        _free_token_exhausted_printed = False

    free_tokens = API_CONFIG.get('free_tokens', [])

    for token in free_tokens:
        if _token_usage.get(token, 0) < _DAILY_LIMIT:
            return token

    # 免费 token 用完，使用付费 token
    if not _free_token_exhausted_printed:
        print(f"⚠️ 智兔 API: 免费 token 全部用完（{len(free_tokens)} 个×{_DAILY_LIMIT} 次），切换到付费 token")
        _free_token_exhausted_printed = True
    return API_CONFIG['token']


def _record_usage(token):
    """记录 token 使用"""
    _token_usage[token] = _token_usage.get(token, 0) + 1


def _mark_token_exhausted(token):
    """标记 token 为耗尽（失败时调用，强制切换到下一个）"""
    _token_usage[token] = _token_usage.get(token, 0) + _DAILY_LIMIT


def _api_request(url_template, **kwargs):
    """
    带重试和 token 故障转移的 API 请求。

    Args:
        url_template: URL 模板，其中 token 部分用 {token} 占位
        **kwargs: 传给 requests.get 的参数（如 timeout）

    Returns:
        响应 JSON 或 None（所有 token 都失败）
    """
    free_tokens = API_CONFIG.get('free_tokens', [])
    max_attempts = len(free_tokens) + 2

    for attempt in range(max_attempts):
        current_token = _get_current_token()
        if not current_token:
            print("智兔 API: 无可用 token")
            return None

        is_free = current_token in free_tokens
        token_label = f"免费token {current_token[:8]}..." if is_free else f"付费token {current_token[:8]}..."

        url = url_template.replace('{token}', current_token)

        # 打印完整请求 URL，方便调试
        print(f"智兔 API 请求: {url}")

        is_403 = False
        try:
            headers = kwargs.pop('headers', {})
            headers.setdefault('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            response = requests.get(url, verify=False, headers=headers, **kwargs)
            response.raise_for_status()
            data = response.json()

            # 打印响应摘要，方便调试
            if isinstance(data, dict):
                print(f"智兔 API 响应: code={data.get('code')}, error={data.get('error')}, keys={list(data.keys())[:5]}")
            elif isinstance(data, list):
                print(f"智兔 API 响应: list length={len(data)}")
            else:
                print(f"智兔 API 响应: type={type(data)}")

            # 检查 API 层面错误
            if isinstance(data, dict) and data.get('error'):
                error_msg = str(data.get('error', ''))
                # 404/资源不存在 是股票代码问题，不是 token 问题，直接返回 None
                if '404' in error_msg or '资源不存在' in error_msg or '参数' in error_msg:
                    print(f"智兔 API: 资源不存在（{token_label}）- 可能是股票代码无效")
                    return None
                # 其他错误（如 token 过期/无效）才切换 token
                print(f"智兔 API 返回错误: {error_msg} ({token_label})")
                _mark_token_exhausted(current_token)
                continue

            # 成功
            _record_usage(current_token)
            usage_count = _token_usage.get(current_token, 0)
            # 每个 token 首次使用、切换 token、以及每 100 次打印一次状态
            if usage_count == 1 or usage_count % 100 == 0:
                print(f"智兔 API: 当前使用 {token_label}，今日已用 {usage_count} 次")
            return data

        except requests.exceptions.Timeout:
            print(f"智兔 API 超时 ({token_label}, 第{attempt+1}次) URL: {url}")
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0
            print(f"智兔 API HTTP {status_code} ({token_label}, 第{attempt+1}次)")
            # 429=超限, 401=无效 → 标记 token 耗尽；403=间歇性拒绝 → 仅重试不标记
            if status_code in (401, 429):
                _mark_token_exhausted(current_token)
            elif status_code == 403:
                is_403 = True  # 不标记，下次重试可能命中其他后端服务器
        except Exception as e:
            print(f"智兔 API 异常: {e} ({token_label}, 第{attempt+1}次)")

        # 失败，标记当前 token 耗尽（403 除外）
        if not is_403:
            _mark_token_exhausted(current_token)
        time.sleep(REQUEST_INTERVAL)

    print("智兔 API: 所有 token 均失败")
    return None


# 兼容旧代码
TOKEN = API_CONFIG['token']

def get_stock_list():
    """
    获取沪深A股股票列表（每次重新拉取，不使用缓存）
    """
    url_template = f"{BASE_URL}/hs/list/all?token={{token}}"
    data = _api_request(url_template, timeout=15)

    if data is None:
        # API 全部失败，尝试从本地加载旧数据作为兜底
        local_data = load_stock_data("stock_list", "all")
        if local_data:
            print("智兔 API 不可用，使用本地缓存的股票列表")
            return local_data
        print("获取股票列表失败: 所有 token 请求失败且无本地缓存")
        return []

    stocks = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                stocks.append({
                    "code": item.get("dm"),
                    "name": item.get("mc"),
                    "exchange": item.get("jys")
                })
    elif isinstance(data, dict):
        if data.get("code") == 200 and data.get("data"):
            for item in data["data"]:
                if isinstance(item, dict):
                    stocks.append({
                        "code": item.get("dm"),
                        "name": item.get("mc"),
                        "exchange": item.get("jys")
                    })
    
    if stocks:
        save_stock_data("stock_list", "all", stocks)
    
    return stocks

def get_stock_realtime_data(stock_code):
    """
    获取股票实时数据（含换手率hs、流通市值lt、总市值sz）
    接口: /hs/real/ssjy/{股票代码}?token={token}
    返回字段: hs(换手率%), lt(流通市值元), sz(总市值元), p(价格), v(成交量万手), ...

    缓存策略：
    - 交易时段（9:30~15:00）：1小时过期（盘中数据会变）
    - 非交易时段（15:00~次日9:30）：18小时过期（收盘后数据不变，拉一次够用）
    """
    import datetime as _dt
    from config import STORAGE_CONFIG

    # 动态计算实时数据缓存有效期
    now = _dt.datetime.now()
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)

    is_weekday = now.weekday() < 5  # 周一~周五
    is_trading_hours = market_open <= now <= market_close

    if is_weekday and is_trading_hours:
        # 工作日交易时段：1小时过期
        realtime_max_age = STORAGE_CONFIG['realtime_data_max_age_hours']
    elif not is_weekday:
        # 周末：66小时过期（覆盖周五收盘到周一开盘）
        realtime_max_age = 66
    else:
        # 工作日非交易时段：18小时过期
        realtime_max_age = 18

    local_data = load_stock_data(f"{stock_code}_realtime", "d",
                                 max_age_hours=realtime_max_age)
    if local_data:
        return local_data

    code_only = stock_code.split('.')[0]
    url_template = f"{BASE_URL}/hs/real/ssjy/{code_only}?token={{token}}"
    data = _api_request(url_template, timeout=10)

    if data is None:
        print(f"获取{stock_code}实时数据失败: 所有 token 请求失败")
        return None

    # 检查是否有有效数据（价格可能为0，但字段必须存在）
    # 智兔实时数据返回格式: {'t': time, 'p': price, 'pc': pre_close, ...}
    if isinstance(data, dict) and 'error' not in data and 'p' in data:
        # 智兔API的lt(流通市值)和sz(总市值)单位已经是元，无需转换
        save_stock_data(f"{stock_code}_realtime", "d", data)
        return data
    else:
        print(f"获取{stock_code}实时数据失败: {data}")
        return None

def get_stock_history_data(stock_code, period="d", limit=100, use_local=True):
    """
    获取股票历史数据
    period: 周期，d=日线, w=周线, m=月线
    limit: 获取数据条数
    use_local: 是否使用本地数据
    """
    # 首先尝试从本地加载数据（按周期使用不同的缓存有效期）
    if use_local:
        from config import STORAGE_CONFIG
        if period == 'w':
            max_age = STORAGE_CONFIG.get('weekly_kline_max_age_hours', 72)
            local_data = load_stock_data(stock_code, period, max_age_hours=max_age)
        else:
            # 日K线使用 18:00 分界线逻辑：
            # 当前时间 >= 18:00 时，只有今天18:00后保存的缓存才有效
            # 当前时间 < 18:00 时，只有昨天18:00后保存的缓存才有效
            # 这确保每天收盘后(21:00 pipeline跑时)一定会重新拉取当天数据
            local_data = load_stock_data(stock_code, period)
        if local_data:
            return local_data
    
    from config import TIME_RANGE_CONFIG
    import datetime
    # 获取时间范围配置
    days = TIME_RANGE_CONFIG['days']
    start_date = TIME_RANGE_CONFIG['start_date']
    end_date = TIME_RANGE_CONFIG['end_date']
    
    # 如果没有指定开始日期，自动计算
    if start_date is None:
        start_date = (datetime.datetime.now() - datetime.timedelta(days=int(days * 1.5))).strftime('%Y%m%d')
    
    # 如果没有指定结束日期，根据当前时间决定
    if end_date is None:
        now = datetime.datetime.now()
        if now.hour >= 18:
            end_date = now.strftime('%Y%m%d')
        else:
            end_date = (now - datetime.timedelta(days=1)).strftime('%Y%m%d')
    
    url_template = f"{BASE_URL}/hs/history/{stock_code}/{period}/n?token={{token}}&st={start_date}&et={end_date}"
    data = _api_request(url_template, timeout=15)

    if data is None:
        print(f"获取股票{stock_code}历史数据失败: 所有 token 请求失败")
        return []

    # 处理不同的数据结构
    result = []
    if isinstance(data, list):
        result = data
    elif isinstance(data, dict):
        if data.get("code") == 200 and data.get("data"):
            result = data["data"]
        elif data.get("error"):
            print(f"API返回错误: {data.get('error', '未知错误')}")
        else:
            print(f"API返回错误: {data.get('message', '未知错误')}")
    
    # 保存数据到本地
    if result:
        save_stock_data(stock_code, period, result)
    
    return result

def get_stock_macd(stock_code, period="d", limit=100):
    """
    获取股票MACD指标
    """
    # 首先尝试从本地加载数据
    local_data = load_stock_data(f"{stock_code}_macd", period)
    if local_data:
        return local_data
    
    # 提取股票代码部分，去掉市场后缀
    code_only = stock_code.split('.')[0]
    url = f"{BASE_URL}/hs/history/macd/{code_only}/{period}?token={_get_current_token()}&limit={limit}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        result = []
        if data.get("code") == 200 and data.get("data"):
            result = data["data"]
        elif data.get("error"):
            print(f"API返回错误: {data.get('error', '未知错误')}")
        
        # 保存数据到本地
        if result:
            save_stock_data(f"{stock_code}_macd", period, result)
        
        return result
    except Exception as e:
        print(f"获取股票{stock_code}MACD数据失败: {str(e)}")
        return []
    finally:
        time.sleep(REQUEST_INTERVAL)

def get_stock_history_data_with_future(stock_code, period="d", limit=100, use_local=True, future_days=5):
    """
    获取股票历史数据（包含未来几天的数据用于回测）
    period: 周期，d=日线, w=周线, m=月线
    limit: 获取数据条数
    use_local: 是否使用本地数据
    future_days: 需要获取的未来天数（用于回测）
    """
    # 首先尝试从本地加载数据
    if use_local:
        local_data = load_stock_data(f"{stock_code}_future", period)
        if local_data:
            return local_data
    
    from config import TIME_RANGE_CONFIG
    import datetime
    # 获取时间范围配置
    days = TIME_RANGE_CONFIG['days']
    start_date = TIME_RANGE_CONFIG['start_date']
    
    # 如果没有指定开始日期，自动计算
    if start_date is None:
        # 为了确保获取足够的数据，增加50%的缓冲
        start_date = (datetime.datetime.now() - datetime.timedelta(days=int(days * 1.5))).strftime('%Y%m%d')
    
    # 结束日期设为今天+future_days，用于获取未来数据进行回测
    end_date = (datetime.datetime.now() + datetime.timedelta(days=future_days)).strftime('%Y%m%d')
    
    url = f"{BASE_URL}/hs/history/{stock_code}/{period}/n?token={_get_current_token()}&st={start_date}&et={end_date}"
    try:
        print(f"请求URL（含未来数据）: {url}")
        response = requests.get(url)
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text[:200]}...")
        response.raise_for_status()
        data = response.json()
        # 处理不同的数据结构
        result = []
        if isinstance(data, list):
            result = data
        elif isinstance(data, dict):
            if data.get("code") == 200 and data.get("data"):
                result = data["data"]
            elif data.get("error"):
                print(f"API返回错误: {data.get('error', '未知错误')}")
            else:
                print(f"API返回错误: {data.get('message', '未知错误')}")
        
        # 保存数据到本地
        if result:
            save_stock_data(f"{stock_code}_future", period, result)
        
        return result
    except Exception as e:
        print(f"获取股票{stock_code}历史数据（含未来）失败: {str(e)}")
        return []
    finally:
        time.sleep(REQUEST_INTERVAL)

def get_stock_ma(stock_code, period="d", limit=100):
    """
    获取股票MA指标
    """
    # 首先尝试从本地加载数据
    local_data = load_stock_data(f"{stock_code}_ma", period)
    if local_data:
        return local_data
    
    # 提取股票代码部分，去掉市场后缀
    code_only = stock_code.split('.')[0]
    url = f"{BASE_URL}/hs/history/ma/{code_only}/{period}?token={_get_current_token()}&limit={limit}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        result = []
        if data.get("code") == 200 and data.get("data"):
            result = data["data"]
        elif data.get("error"):
            print(f"API返回错误: {data.get('error', '未知错误')}")
        
        # 保存数据到本地
        if result:
            save_stock_data(f"{stock_code}_ma", period, result)
        
        return result
    except Exception as e:
        print(f"获取股票{stock_code}MA数据失败: {str(e)}")
        return []
    finally:
        time.sleep(REQUEST_INTERVAL)
