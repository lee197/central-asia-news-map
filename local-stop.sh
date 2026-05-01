#!/bin/bash
# 停止本地开发的后端和前端
echo "停止本地服务..."
lsof -ti:8765 | xargs kill -9 2>/dev/null && echo "  ✓ 后端已停" || echo "  - 后端未在跑"
lsof -ti:8764 | xargs kill -9 2>/dev/null && echo "  ✓ 前端已停" || echo "  - 前端未在跑"
