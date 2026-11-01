#!/bin/zsh
cd -- "${0:A:h}" || exit 1
exec python3 -B scripts/remote_access.py
