#!/bin/bash
# Double-click launcher: always uses project venv, never system Python.
cd "$(dirname "$0")" || exit 1

VENV_PYTHON="./venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "找不到项目虚拟环境: $VENV_PYTHON"
  echo "请先创建 venv 并安装依赖: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
  read -r -p "按回车关闭…"
  exit 1
fi

exec "$VENV_PYTHON" run.py
