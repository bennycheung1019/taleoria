#!/usr/bin/env python3
"""Friendly entry point; all paths follow this folder rather than the shell cwd."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit('請先安裝 Python 3.11 或以上：https://www.python.org/downloads/')

if __name__ == '__main__':
    from server import main
    if '--open-browser' not in sys.argv:
        sys.argv.append('--open-browser')
    main()
