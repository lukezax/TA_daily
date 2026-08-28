import os
import json
import datetime

# 失败列表存储文件
FAILED_LIST_FILE = 'failed_stocks.json'

# 确保文件存在
if not os.path.exists(FAILED_LIST_FILE):
    with open(FAILED_LIST_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)

def add_failed_stock(stock, error_message):
    """
    添加失败的股票到失败列表
    """
    try:
        with open(FAILED_LIST_FILE, 'r', encoding='utf-8') as f:
            failed_stocks = json.load(f)
        
        # 检查是否已经存在
        for item in failed_stocks:
            if item['code'] == stock['code']:
                # 更新错误信息和时间戳
                item['error_message'] = error_message
                item['timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                break
        else:
            # 添加新的失败股票
            failed_stocks.append({
                'code': stock['code'],
                'name': stock['name'],
                'exchange': stock['exchange'],
                'error_message': error_message,
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
        
        with open(FAILED_LIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(failed_stocks, f, ensure_ascii=False, indent=2)
        
        print(f"已将股票 {stock['code']} 添加到失败列表")
    except Exception as e:
        print(f"添加失败股票到列表时出错: {str(e)}")

def get_failed_stocks():
    """
    获取失败股票列表
    """
    try:
        with open(FAILED_LIST_FILE, 'r', encoding='utf-8') as f:
            failed_stocks = json.load(f)
        return failed_stocks
    except Exception as e:
        print(f"获取失败股票列表时出错: {str(e)}")
        return []

def remove_failed_stock(stock_code):
    """
    从失败列表中移除股票
    """
    try:
        with open(FAILED_LIST_FILE, 'r', encoding='utf-8') as f:
            failed_stocks = json.load(f)
        
        # 过滤掉指定的股票
        failed_stocks = [item for item in failed_stocks if item['code'] != stock_code]
        
        with open(FAILED_LIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(failed_stocks, f, ensure_ascii=False, indent=2)
        
        print(f"已从失败列表中移除股票 {stock_code}")
    except Exception as e:
        print(f"从失败列表中移除股票时出错: {str(e)}")

def clear_failed_stocks():
    """
    清空失败股票列表
    """
    try:
        with open(FAILED_LIST_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
        print("已清空失败股票列表")
    except Exception as e:
        print(f"清空失败股票列表时出错: {str(e)}")
