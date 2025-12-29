#!/usr/bin/env bash
set -euo pipefail

python src/reset_all.py
python src/main.py
exec python -m http.server 8000
