#!/usr/bin/env bash
# Start the full travel project UI (Streamlit).
# Usage: ./travel/run_local.sh   (from travel_code parent directory)

set -euo pipefail
TRAVEL_ROOT="$(cd "$(dirname "$0")" && pwd)"
TRAVEL_CODE_ROOT="$(dirname "$TRAVEL_ROOT")"
cd "$TRAVEL_CODE_ROOT"

echo "Installing Python dependencies..."
python -m pip install -q -r "$TRAVEL_ROOT/requirements.txt"

echo "Ensuring demo pins exist..."
python "$TRAVEL_ROOT/bootstrap_demo.py"

echo "Starting UI at http://localhost:8501"
echo "Use the sidebar: Home -> Pin Intelligence -> Atlas Explorer"
exec python -m streamlit run "$TRAVEL_ROOT/app_home.py"
