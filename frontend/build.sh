#!/bin/bash
# Render 构建脚本：把环境变量注入到 index.html，输出到 dist/
set -e

mkdir -p dist

# 检查必需的环境变量
: "${AMAP_KEY:?ERROR: AMAP_KEY env var is required (set it in Render dashboard)}"
: "${API_BASE:?ERROR: API_BASE env var is required (e.g. https://news-map-api.onrender.com)}"

echo "Building frontend with:"
echo "  AMAP_KEY  = ${AMAP_KEY:0:6}... (length=${#AMAP_KEY})"
echo "  API_BASE  = $API_BASE"

# 替换占位符
sed \
  -e "s|__AMAP_KEY__|${AMAP_KEY}|g" \
  -e "s|__API_BASE__|${API_BASE}|g" \
  index.html > dist/index.html

echo "✓ dist/index.html generated ($(wc -c < dist/index.html) bytes)"
