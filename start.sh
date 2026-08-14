#!/usr/bin/env bash
# ActionFlow 一键演示启动（macOS / Linux）
# 用法：bash start.sh        —— 启动并自动打开浏览器
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "首次运行，正在创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi

if [ -f .env ]; then
  set -a; # shellcheck disable=SC1091
  source .env; set +a
fi

export APP_PORT="${APP_PORT:-8766}"
echo ""
echo "  ActionFlow 会议协同工作台"
echo "  ----------------------------------------"
echo "  地址:  http://127.0.0.1:${APP_PORT}"
echo "  停止:  Ctrl + C"
echo ""
( sleep 1.5; open "http://127.0.0.1:${APP_PORT}" 2>/dev/null || xdg-open "http://127.0.0.1:${APP_PORT}" 2>/dev/null || true ) &
exec ./.venv/bin/python app.py
