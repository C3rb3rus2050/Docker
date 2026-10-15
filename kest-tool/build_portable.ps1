# Build on Windows 11 with Python 3.12 installed on the BUILD machine only.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -3.12 -m venv .build-venv
$python = Join-Path $PSScriptRoot ".build-venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt pyinstaller
& $python -m PyInstaller --noconfirm --clean --onedir --name KESt-Tool --collect-all streamlit --collect-all altair --collect-all pyarrow --collect-all pdfplumber --collect-all fitz --add-data "app.py;." --add-data "config.yaml;." --add-data ".streamlit;.streamlit" --add-data "src;src" portable_launcher.py
if ($LASTEXITCODE -ne 0) { throw "Build fehlgeschlagen" }
$target = Join-Path $PSScriptRoot "dist\KESt-Tool"
New-Item -ItemType Directory -Force -Path (Join-Path $target "Daten") | Out-Null
Compress-Archive -Path $target -DestinationPath (Join-Path $PSScriptRoot "dist\KESt-Tool-Portable-Windows.zip") -Force
Write-Host "Fertig: dist\KESt-Tool-Portable-Windows.zip"
