import os
import json
import datetime
from config import STORAGE_CONFIG

DATA_DIR = 'stock_data'

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

USE_LOCAL_DATA = STORAGE_CONFIG['use_local_data']
MAX_DATA_AGE_HOURS = STORAGE_CONFIG['max_data_age_hours']
REALTIME_DATA_MAX_AGE_HOURS = STORAGE_CONFIG['realtime_data_max_age_hours']


def get_data_file_path(stock_code, period):
    return os.path.join(DATA_DIR, f"{stock_code}_{period}.json")


def _is_expired(timestamp: datetime.datetime, stock_code: str, max_age_hours: float = None) -> bool:
    """
    判断缓存是否过期。

    如果指定了 max_age_hours：距保存时间超过该小时数则过期（简单时间差判断）
    如果未指定：使用"18:00 分界线"逻辑（向后兼容）
    """
    now = datetime.datetime.now()

    # 如果指定了 max_age_hours，用简单的时间差判断
    if max_age_hours is not None:
        age = (now - timestamp).total_seconds() / 3600
        return age > max_age_hours

    # 未指定时，使用原有的 18:00 分界线逻辑
    today_18 = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now >= today_18:
        cutoff = today_18
    else:
        cutoff = today_18 - datetime.timedelta(days=1)
        if timestamp.date() == now.date():
            return False

    return timestamp < cutoff


def save_stock_data(stock_code, period, data):
    file_path = get_data_file_path(stock_code, period)
    data_with_timestamp = {
        'data': data,
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data_with_timestamp, f, ensure_ascii=False, indent=2)
    print(f"股票数据已保存到本地: {file_path}")


def load_stock_data(stock_code, period, max_age_hours=None):
    """
    从本地文件加载股票数据。

    Args:
        stock_code: 股票代码
        period: 数据周期
        max_age_hours: 缓存最大有效时间（小时）。
                       传入时用简单时间差判断过期；
                       不传时用 18:00 分界线逻辑（向后兼容）。
    """
    if not USE_LOCAL_DATA:
        return None

    file_path = get_data_file_path(stock_code, period)
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data_with_timestamp = json.load(f)

        timestamp_str = data_with_timestamp.get('timestamp')
        if not timestamp_str:
            return None

        timestamp = datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

        if _is_expired(timestamp, stock_code, max_age_hours=max_age_hours):
            print(f"本地数据已过期（保存于 {timestamp_str}），需要重新获取")
            return None

        return data_with_timestamp.get('data', [])
    except Exception as e:
        print(f"加载本地数据失败: {str(e)}")
        return None


def clear_expired_data(max_age_hours=None):
    if not os.path.exists(DATA_DIR):
        return

    for filename in os.listdir(DATA_DIR):
        if not filename.endswith('.json'):
            continue
        file_path = os.path.join(DATA_DIR, filename)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data_with_timestamp = json.load(f)
            timestamp_str = data_with_timestamp.get('timestamp')
            if timestamp_str:
                timestamp = datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                stock_code = filename.replace('.json', '')
                if _is_expired(timestamp, stock_code):
                    os.remove(file_path)
                    print(f"已清理过期数据: {filename}")
        except Exception as e:
            print(f"清理数据文件失败: {str(e)}")
