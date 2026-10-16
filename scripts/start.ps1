$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path 'frontend\dist\index.html') -or -not (Test-Path '.venv\Scripts\python.exe')) {
    throw 'Zuerst scripts\setup.ps1 ausführen.'
}
$env:PYTHONPATH = Join-Path (Get-Location) 'kest-tool\src'
Write-Host 'KESt Manager: http://127.0.0.1:8000/steuer/ · Beenden mit Strg+C'
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
