# Windows setup script for the Ansible dev environment
# Usage:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"

Write-Host "== Platypus Ansible dev env setup ==" -ForegroundColor Cyan

# 1) Check for Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Please install it from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

# 2) Create the virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host ">> Creating Python virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

# 3) Activate the venv and install dependencies
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

# 4) Install Ansible collections
Write-Host ">> Installing Ansible collections..." -ForegroundColor Yellow
& ".venv\Scripts\ansible-galaxy.exe" collection install -r requirements.yml -p collections

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "Activate the environment with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "Verify with:                  ansible --version" -ForegroundColor Cyan
