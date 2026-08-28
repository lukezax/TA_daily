#!/bin/bash
# stock_filter.py 最小打包脚本 - 目标: macOS 15
set -e

echo "=== 打包 stock_filter ==="

DIST=dist/stock_filter
rm -rf "$DIST"
mkdir -p "$DIST/stock_data" "$DIST/logs"

echo "[1/3] 复制源文件..."
for f in stock_filter.py api.py config.py data_storage.py \
         feishu_notify.py filter.py mock_data.py retry_manager.py \
         requirements.txt; do
  cp "$f" "$DIST/"
done

echo "[2/3] 复制文档..."
for f in 使用说明.md 筛选逻辑实现说明.md 筛选逻辑与代码实现对应关系.md \
         ARCHITECTURE.md DEPLOYMENT.md; do
  [ -f "$f" ] && cp "$f" "$DIST/"
done

echo "[3/3] 生成启动脚本..."
cat > "$DIST/run.sh" << 'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if ! command -v python3 &>/dev/null; then
  echo "错误: 未找到 python3，请先安装: brew install python"
  exit 1
fi

# 首次运行安装依赖
if ! python3 -c "import flask" &>/dev/null; then
  echo "安装依赖..."
  pip3 install -r requirements.txt
fi

python3 stock_filter.py "$@"
EOF
chmod +x "$DIST/run.sh"

(cd dist && zip -r stock_filter_macos.zip stock_filter/)

echo ""
echo "=== 完成: dist/stock_filter_macos.zip ==="
echo "用法: unzip → cd stock_filter → ./run.sh --strategy b1 --test"
