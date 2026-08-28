from flask import Blueprint, request, jsonify
import json
import os

auth_bp = Blueprint('auth', __name__)

# 模拟用户数据存储
USERS_FILE = 'users.json'

# 加载用户数据
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f'加载用户数据失败: {str(e)}')
            return {}
    return {}

# 保存用户数据
def save_users(users):
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'保存用户数据失败: {str(e)}')

# 初始化用户数据
users = load_users()

# 注册接口
@auth_bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        email = data.get('email')
        
        if not username or not password or not email:
            return jsonify({
                'status': 'error',
                'message': '用户名、密码和邮箱不能为空'
            }), 400
        
        if username in users:
            return jsonify({
                'status': 'error',
                'message': '用户名已存在'
            }), 400
        
        # 保存用户信息（实际应用中应该对密码进行加密）
        users[username] = {
            'password': password,
            'email': email,
            'created_at': os.path.getmtime(USERS_FILE) if os.path.exists(USERS_FILE) else 0
        }
        
        save_users(users)
        
        return jsonify({
            'status': 'success',
            'message': '注册成功'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# 登录接口
@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({
                'status': 'error',
                'message': '用户名和密码不能为空'
            }), 400
        
        user = users.get(username)
        if not user or user.get('password') != password:
            return jsonify({
                'status': 'error',
                'message': '用户名或密码错误'
            }), 401
        
        # 实际应用中应该生成JWT token
        return jsonify({
            'status': 'success',
            'message': '登录成功',
            'data': {
                'username': username,
                'email': user.get('email')
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# 获取用户信息接口
@auth_bp.route('/user/<username>', methods=['GET'])
def get_user(username):
    try:
        user = users.get(username)
        if not user:
            return jsonify({
                'status': 'error',
                'message': '用户不存在'
            }), 404
        
        return jsonify({
            'status': 'success',
            'data': {
                'username': username,
                'email': user.get('email')
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# 注销接口
@auth_bp.route('/logout', methods=['POST'])
def logout():
    try:
        # 实际应用中应该处理token注销
        return jsonify({
            'status': 'success',
            'message': '注销成功'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500