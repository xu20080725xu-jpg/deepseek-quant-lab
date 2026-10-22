#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  echo "首次使用请先运行：python3 -m venv .venv，然后 .venv/bin/python -m pip install -r requirements.txt"
  read "?按回车关闭"
  exit 1
fi
exec .venv/bin/python -m streamlit run app.py --server.address=127.0.0.1
