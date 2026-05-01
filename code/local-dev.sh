#!/bin/bash
# 本地开发：启动后端（mock 模式）+ 在浏览器打开前端
# 用法：bash local-dev.sh [your-amap-key]

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$DIR/backend"
FRONTEND="$DIR/frontend"

AMAP_KEY="${1:-PLEASE_REPLACE_WITH_YOUR_AMAP_KEY}"

echo "========================================"
echo "  中亚新闻地图 · 本地开发模式"
echo "========================================"

# 后端
echo "[1/3] 启动后端 (mock 模式)..."
cd "$BACKEND"
if [ ! -d "venv" ]; then
  python3 -m venv venv
  ./venv/bin/pip install -q -r requirements.txt
fi

# 杀掉之前可能在跑的实例
lsof -ti:8765 | xargs kill -9 2>/dev/null || true

USE_MOCK=true ./venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765 > /tmp/news-map-backend.log 2>&1 &
BACKEND_PID=$!
echo "  后端 PID=$BACKEND_PID, 日志: /tmp/news-map-backend.log"

# 等后端起来
for i in {1..20}; do
  if curl -s http://127.0.0.1:8765/api/health > /dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! curl -s http://127.0.0.1:8765/api/health > /dev/null 2>&1; then
  echo "  ✗ 后端启动失败，看日志：cat /tmp/news-map-backend.log"
  exit 1
fi
echo "  ✓ 后端运行中: http://127.0.0.1:8765"

# 前端：把占位符替换成本地配置
echo "[2/3] 准备前端..."
TMP_FRONTEND="/tmp/news-map-frontend-dev"
mkdir -p "$TMP_FRONTEND"
sed \
  -e "s|__AMAP_KEY__|$AMAP_KEY|g" \
  -e "s|__API_BASE__|http://127.0.0.1:8765|g" \
  "$FRONTEND/index.html" > "$TMP_FRONTEND/index.html"
echo "  ✓ 前端已生成: $TMP_FRONTEND/index.html"

# 启个简单 HTTP 服务器
echo "[3/3] 启动前端服务..."
lsof -ti:8764 | xargs kill -9 2>/dev/null || true
cd "$TMP_FRONTEND"
python3 -m http.server 8764 > /tmp/news-map-frontend.log 2>&1 &
FRONTEND_PID=$!
sleep 1
echo "  ✓ 前端运行中: http://127.0.0.1:8764"

echo ""
echo "========================================"
echo "  全部就绪！"
echo "========================================"
echo "  打开浏览器: http://127.0.0.1:8764"
echo ""
echo "  停止服务："
echo "    kill $BACKEND_PID $FRONTEND_PID"
echo "  或："
echo "    bash $DIR/local-stop.sh"
echo ""
echo "  日志:"
echo "    后端: tail -f /tmp/news-map-backend.log"
echo "    前端: tail -f /tmp/news-map-frontend.log"
