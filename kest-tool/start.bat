@echo off
setlocal
chcp 65001 >nul
title KESt-Tool
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [FEHLER] Die Anwendung ist noch nicht installiert. Bitte zuerst install.bat ausfuehren.
    pause
    exit /b 1
)

rem Optionale Umgebungsvariablen aus .env laden (keine Zugangsdaten!)
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" set "%%A=%%B"
    )
)

echo ============================================================
echo  KESt-Tool startet. Die Oberflaeche oeffnet sich im Browser:
echo     http://localhost:8501
echo  Nur lokal erreichbar. Zum Beenden dieses Fenster schliessen
echo  oder Strg+C druecken.
echo ============================================================
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [HINWEIS] Das Programm wurde mit Code %RC% beendet. Details: Ablageordner\logs\kest_tool.log
    pause
)
exit /b %RC%
