@echo off
setlocal
chcp 65001 >nul
title Broker Document Collector
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [FEHLER] Die Anwendung ist noch nicht installiert. Bitte zuerst install.bat ausfuehren.
    pause
    exit /b 1
)

rem Alle Parameter werden durchgereicht, z. B.:
rem   start_collector.bat               - Oberflaeche starten
rem   start_collector.bat --sync        - Inkrementelle Synchronisierung (Aufgabenplaner)
rem   start_collector.bat --help        - Alle Optionen
".venv\Scripts\python.exe" collector.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [HINWEIS] Das Programm wurde mit Code %RC% beendet. Details im Ordner logs des Ausgabeordners.
    if /i not "%~1"=="--sync" pause
)
exit /b %RC%
