#!/bin/zsh
cd -- "${0:A:h}"
if ! command -v python3 >/dev/null 2>&1; then
  echo '請先安裝 Python 3.11 或以上：https://www.python.org/downloads/macos/'
else
  python3 -B taleoria.py
fi
echo 'Taleoria 已停止。按 Enter 關閉。'
read -r
