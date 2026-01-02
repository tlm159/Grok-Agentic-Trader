#!/usr/bin/env bash
set -euo pipefail

python3 src/reset_all.py
python3 src/main.py
exec python3 -m http.server 8000
