# Install the desktop agent into a local virtualenv.
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.11+ is required and was not found on PATH."
}

python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[ocr,dev]"

Write-Host ""
Write-Host "Installed. Activate with: .\.venv\Scripts\Activate.ps1"
Write-Host "Install Tesseract so the default OCR engine can run."
Write-Host "Install MilesMemory for long-term recall: pip install -e path\to\MilesMemory"
Write-Host "Leave VISION_ALLOW_SCREEN_CONTROL unset until you intend to move the mouse."
