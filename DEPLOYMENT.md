# 股票筛选系统部署文档

## 1. 本地开发环境部署

### 1.1 安装依赖

```bash
pip install -r requirements.txt
```

### 1.2 启动应用

```bash
python app.py
```

应用将在 http://localhost:5000 启动。

## 2. Docker容器化部署

### 2.1 构建镜像

```bash
docker build -t stock-filter .
```

### 2.2 运行容器

```bash
docker run -p 5000:5000 --name stock-filter stock-filter
```

### 2.3 使用docker-compose

```bash
docker-compose up -d
```

## 3. 公网部署

### 3.1 服务器准备

1. 购买云服务器（推荐使用阿里云、腾讯云等）
2. 安装Docker和docker-compose
3. 配置防火墙，开放5000端口

### 3.2 部署步骤

1. 克隆代码到服务器

```bash
git clone <仓库地址>
cd stock
```

2. 构建并运行容器

```bash
docker-compose up -d
```

3. 配置域名（可选）

- 购买域名并解析到服务器IP
- 配置Nginx反向代理（示例配置）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## 4. 环境变量配置

应用支持以下环境变量：

- `FLASK_ENV`: 运行环境（development/production）
- `HOST`: 绑定的主机地址
- `PORT`: 监听的端口号

## 5. 自动执行配置

系统已内置定时任务，每天08:30自动执行B1和超短策略。

## 6. 日志管理

执行历史记录存储在 `execution_history.json` 文件中，可用于查看执行状态和结果。

## 7. 故障排查

### 7.1 应用无法启动

- 检查端口是否被占用
- 检查依赖是否安装正确
- 查看控制台输出的错误信息

### 7.2 自动执行失败

- 检查网络连接是否正常
- 查看执行历史记录中的错误信息
- 检查API调用是否正常