#!/bin/zsh
cd "$(dirname "$0")" || exit 1
exec python3 -B taleoria.py --config taleoria.preproduction.json
