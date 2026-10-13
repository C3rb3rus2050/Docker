@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Broker Document Collector - Installation
cd /d "%~dp0"

echo ============================================================
echo  Broker Document Collector - Installation
echo ============================================================
echo.

rem --- 1. Python suchen (3.11 oder neuer, empfohlen 3.12) ------------------
set "PY="
for %%V in (3.12 3.13 3.11) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [FEHLER] Keine kompatible Python-Version gefunden ^(benoetigt: 3.11 oder neuer, empfohlen 3.12^).
    echo          Bitte Python von https://www.python.org/downloads/windows/ installieren
    echo          und bei der Installation "Add python.exe to PATH" aktivieren.
    echo          Administratorrechte sind dafuer NICHT erforderlich ^("Install for current user"^).
    goto :fail
)
for /f "delims=" %%I in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%I"
echo [OK] Python !PYVER! gefunden ^(%PY%^)

rem --- 2. Virtuelle Umgebung --------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [..] Erstelle virtuelle Umgebung .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [FEHLER] Die virtuelle Umgebung konnte nicht erstellt werden.
        goto :fail
    )
)
echo [OK] Virtuelle Umgebung vorhanden
set "VPY=.venv\Scripts\python.exe"

rem --- 3. Abhaengigkeiten -----------------------------------------------------
echo [..] Installiere Abhaengigkeiten ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [FEHLER] Abhaengigkeiten konnten nicht installiert werden. Internetverbindung pruefen.
    goto :fail
)
echo [OK] Abhaengigkeiten installiert

rem --- 4. Playwright Chromium -------------------------------------------------
echo [..] Installiere Playwright-Chromium ^(einmalig, ca. 150 MB^) ...
"%VPY%" -m playwright install chromium
if errorlevel 1 (
    echo [FEHLER] Chromium fuer Playwright konnte nicht installiert werden.
    goto :fail
)
echo [OK] Chromium installiert

rem --- 5. Lokale Ordner -------------------------------------------------------
if not exist "config.toml" (
    copy /y "config.example.toml" "config.toml" >nul
    echo [OK] config.toml aus Vorlage erstellt
)
"%VPY%" -c "import sys; sys.path.insert(0, 'src'); from broker_collector.config import load_settings; s = load_settings(); s.ensure_dirs(); print('[OK] Ausgabeordner:', s.output_dir); print('[OK] Browserprofil:', s.profile_dir)"
if errorlevel 1 (
    echo [FEHLER] Die lokalen Ordner konnten nicht angelegt werden. config.toml pruefen.
    goto :fail
)

rem --- 6. Selbsttest (optional, schnell) --------------------------------------
echo [..] Fuehre Selbsttest aus ...
"%VPY%" -m pytest -q -m "not live and not integration" >nul 2>&1
if errorlevel 1 (
    echo [WARNUNG] Selbsttest nicht erfolgreich. Details: .venv\Scripts\python -m pytest -q
) else (
    echo [OK] Selbsttest erfolgreich
)

echo.
echo ============================================================
echo  Installation abgeschlossen. Start mit: start.bat
echo ============================================================
pause
exit /b 0

:fail
echo.
echo Installation abgebrochen.
pause
exit /b 1
