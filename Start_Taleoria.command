#!/bin/zsh
cd -- "${0:A:h}" || exit 1
exec python3 -B taleoria.py --config taleoria.preproduction.json
