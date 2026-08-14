#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt
echo "→ http://127.0.0.1:8001"
uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
