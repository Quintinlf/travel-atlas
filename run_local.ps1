# Start the full travel project UI (Streamlit).
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File travel\run_local.ps1

$ErrorActionPreference = "Stop"
$TravelRoot = $PSScriptRoot
$TravelCodeRoot = Split-Path $TravelRoot -Parent

Set-Location $TravelCodeRoot

Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
python -m pip install -q -r (Join-Path $TravelRoot "requirements.txt")

Write-Host "Ensuring demo pins exist..." -ForegroundColor Cyan
python (Join-Path $TravelRoot "bootstrap_demo.py")

$app = Join-Path $TravelRoot "app_home.py"
Write-Host "Starting UI at http://localhost:8501" -ForegroundColor Green
Write-Host "Use the sidebar: Home -> Pin Intelligence -> Atlas Explorer" -ForegroundColor Green

python -m streamlit run $app
