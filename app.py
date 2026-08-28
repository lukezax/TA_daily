from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import os
import time
import json

from api import get_stock_list, get_stock_history_data
from filter import b1_strategy_filter, ultra_short_strategy_filter
from auth import auth_bp

app = Flask(__name__)
CORS(app)

# 注册认证蓝图
app.register_blueprint(auth_bp, url_prefix='/api/auth')

# 初始化调度器
scheduler = BackgroundScheduler()
scheduler.start()

# 执行历史记录
execution_history = []

# 筛选结果存储
filter_results = {}

# 当前执行状态
current_execution = {
    'is_running': False,
    'logs': [],
    'strategy': None,
    'should_stop': False
}

# 首页
@app.route('/')
def index():
    return render_template('index.html')

# 结果页面
@app.route('/results')
def results():
    return render_template('results.html')

# 历史记录页面
@app.route('/history')
def history():
    return render_template('history.html')

# API: 触发筛选
@app.route('/api/filter', methods=['POST'])
def trigger_filter():
    global current_execution
    try:
        strategy = request.json.get('strategy', 'ultra_short')
        
        # 检查是否正在执行
        if current_execution['is_running']:
            return jsonify({
                'status': 'error',
                'message': '已有筛选任务正在执行中'
            }), 400
        
        # 记录开始时间
        start_time = time.strftime('%Y-%m-%d %H:%M:%S')
        
        # 设置执行状态
        current_execution['is_running'] = True
        current_execution['logs'] = []
        current_execution['strategy'] = strategy
        
        # 获取股票列表
        all_stocks = get_stock_list()
        
        # 剔除创业板股票（代码以 300、301、302 开头的）和 ST 股票
        stocks = []
        for stock in all_stocks:
            code = stock['code'].split('.')[0]
            name = stock['name']
            if not (code.startswith('300') or code.startswith('301') or code.startswith('302')) and not name.startswith('ST') and not name.startswith('*ST'):
                stocks.append(stock)
        
        # 筛选结果
        results = []
        total_stocks = len(stocks)
        processed_stocks = 0
        
        add_log(f'开始筛选，共 {total_stocks} 只股票（已剔除创业板和 ST 股票），策略：{strategy}')
        for stock in stocks:
            # 检查是否需要停止
            if current_execution['should_stop']:
                add_log('筛选已被用户停止，本次结果不记录')
                current_execution['is_running'] = False
                current_execution['should_stop'] = False
                return jsonify({
                    'status': 'stopped',
                    'message': '筛选已被用户停止，本次结果不记录',
                    'data': [],
                    'total_processed': processed_stocks,
                    'total_found': len(results)
                })
            
            stock_code = stock.get('code')
            stock_name = stock.get('name')
            
            if stock_code:
                # 获取股票历史数据
                daily_data = get_stock_history_data(stock_code, period='d')
                weekly_data = get_stock_history_data(stock_code, period='w')
                
                if daily_data:
                    # 根据策略进行筛选
                    if strategy == 'b1':
                        result = b1_strategy_filter(daily_data, weekly_data)
                    else:
                        result = ultra_short_strategy_filter(daily_data)
                    
                    if result and result.get('result', False):
                        results.append({
                            'code': stock_code,
                            'name': stock_name,
                            'indicators': result.get('indicators', {}),
                            'conditions': result.get('conditions', {})
                        })
                
                processed_stocks += 1
                if processed_stocks % 50 == 0:
                    add_log(f'已处理 {processed_stocks}/{total_stocks} 只股票')
        
        # 记录结束时间
        end_time = time.strftime('%Y-%m-%d %H:%M:%S')
        
        # 保存结果
        filter_results[strategy] = results
        
        # 记录执行历史
        history_entry = {
            'time': end_time,
            'strategy': strategy,
            'status': 'success',
            'total_stocks': total_stocks,
            'filtered_stocks': len(results),
            'start_time': start_time,
            'end_time': end_time
        }
        execution_history.append(history_entry)
        
        # 保存历史记录到文件
        save_execution_history()
        
        add_log(f'筛选完成，找到 {len(results)} 只符合条件的股票')
        
        # 重置执行状态
        current_execution['is_running'] = False
        
        return jsonify({
            'status': 'success',
            'message': f'筛选已完成，策略：{strategy}，找到 {len(results)} 只符合条件的股票',
            'data': results,
            'total_processed': processed_stocks,
            'total_found': len(results)
        })
    except Exception as e:
        # 重置执行状态
        current_execution['is_running'] = False
        
        # 记录错误历史
        error_entry = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'strategy': request.json.get('strategy', 'ultra_short'),
            'status': 'error',
            'message': str(e)
        }
        execution_history.append(error_entry)
        save_execution_history()
        
        return jsonify({
            'status': 'error',
            'message': str(e)
        })


# API: 获取执行日志
@app.route('/api/execution/logs')
def get_execution_logs():
    return jsonify({
        'status': 'success',
        'is_running': current_execution['is_running'],
        'logs': current_execution['logs'],
        'strategy': current_execution['strategy']
    })


# API: 停止筛选
@app.route('/api/stop', methods=['POST'])
def stop_filter():
    global current_execution
    if current_execution['is_running']:
        current_execution['should_stop'] = True
        add_log('正在停止筛选，请稍候...')
        return jsonify({
            'status': 'success',
            'message': '已发送停止请求，正在停止筛选...'
        })
    else:
        return jsonify({
            'status': 'error',
            'message': '当前没有正在执行的筛选任务'
        })


def add_log(message):
    """全局 add_log 函数，用于在 stop API 中使用"""
    global current_execution
    if current_execution.get('logs') is not None:
        current_execution['logs'].append({
            'time': time.strftime('%H:%M:%S'),
            'message': message
        })
        print(message)

# API: 获取执行状态
@app.route('/api/status')
def get_status():
    last_executed = execution_history[-1]['time'] if execution_history else '从未执行'
    return jsonify({
        'status': 'running',
        'last_executed': last_executed,
        'next_scheduled': '2026-03-07 08:30:00'
    })

# API: 获取筛选结果
@app.route('/api/results/<strategy>')
def get_results(strategy):
    results = filter_results.get(strategy, [])
    return jsonify({
        'status': 'success',
        'data': results,
        'count': len(results)
    })

# API: 获取历史执行详情
@app.route('/api/history/<int:index>')
def get_history_detail(index):
    try:
        if index < 0 or index >= len(execution_history):
            return jsonify({
                'status': 'error',
                'message': '索引超出范围'
            }), 404
        
        record = execution_history[index]
        strategy = record.get('strategy')
        results = filter_results.get(strategy, [])
        
        return jsonify({
            'status': 'success',
            'data': {
                'record': record,
                'results': results
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# API: 获取执行历史
@app.route('/api/history')
def get_history():
    return jsonify({
        'status': 'success',
        'data': execution_history
    })

# 保存执行历史到文件
def save_execution_history():
    try:
        with open('execution_history.json', 'w', encoding='utf-8') as f:
            json.dump(execution_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'保存执行历史失败：{str(e)}')

# 加载执行历史
def load_execution_history():
    global execution_history
    try:
        if os.path.exists('execution_history.json'):
            with open('execution_history.json', 'r', encoding='utf-8') as f:
                execution_history = json.load(f)
    except Exception as e:
        print(f'加载执行历史失败：{str(e)}')

# 自动执行任务
def auto_execute_strategies():
    print(f'自动执行策略：{time.strftime("%Y-%m-%d %H:%M:%S")}')
    # 执行 B1 策略
    trigger_filter_internal('b1')
    # 执行超短线策略
    trigger_filter_internal('ultra_short')

# 内部触发筛选函数
def trigger_filter_internal(strategy):
    try:
        # 记录开始时间
        start_time = time.strftime('%Y-%m-%d %H:%M:%S')
        
        # 获取股票列表
        stocks = get_stock_list()
        
        # 筛选结果
        results = []
        total_stocks = len(stocks)
        processed_stocks = 0
        
        print(f'自动执行：开始筛选，共 {total_stocks} 只股票，策略：{strategy}')
        for stock in stocks:
            stock_code = stock.get('code')
            stock_name = stock.get('name')
            
            if stock_code:
                # 获取股票历史数据
                daily_data = get_stock_history_data(stock_code, period='d')
                weekly_data = get_stock_history_data(stock_code, period='w')
                
                if daily_data:
                    # 根据策略进行筛选
                    if strategy == 'b1':
                        result = b1_strategy_filter(daily_data, weekly_data)
                    else:
                        result = ultra_short_strategy_filter(daily_data)
                    
                    if result and result.get('result', False):
                        results.append({
                            'code': stock_code,
                            'name': stock_name,
                            'indicators': result.get('indicators', {}),
                            'conditions': result.get('conditions', {})
                        })
                
                processed_stocks += 1
                if processed_stocks % 50 == 0:
                    print(f'已处理 {processed_stocks}/{total_stocks} 只股票')
        
        # 记录结束时间
        end_time = time.strftime('%Y-%m-%d %H:%M:%S')
        
        # 保存结果
        filter_results[strategy] = results
        
        # 记录执行历史
        history_entry = {
            'time': end_time,
            'strategy': strategy,
            'status': 'success',
            'total_stocks': total_stocks,
            'filtered_stocks': len(results),
            'start_time': start_time,
            'end_time': end_time
        }
        execution_history.append(history_entry)
        
        # 保存历史记录到文件
        save_execution_history()
        
        print(f'自动执行完成，策略：{strategy}，找到 {len(results)} 只符合条件的股票')
    except Exception as e:
        # 记录错误历史
        error_entry = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'strategy': strategy,
            'status': 'error',
            'message': str(e)
        }
        execution_history.append(error_entry)
        save_execution_history()
        
        print(f'自动执行失败：{str(e)}')

if __name__ == '__main__':
    # 加载执行历史
    load_execution_history()
    
    # 添加定时任务，每天 08:30 执行
    scheduler.add_job(
        auto_execute_strategies,
        'cron',
        hour=8,
        minute=30,
        id='auto_execute',
        replace_existing=True
    )
    
    # 创建必要的目录
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
