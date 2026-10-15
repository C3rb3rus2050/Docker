# KESt-Tool Portable (Windows 11)

Die Windows-Version nutzt denselben Streamlit-Code wie die Docker-Webapp. Sie startet einen lokalen Server nur auf 127.0.0.1 und öffnet die Oberfläche im Standardbrowser. Keine Installation auf dem Ziel-PC erforderlich.

## Build

Auf einem **Windows-Build-PC** mit Python 3.12:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable.ps1
```

Die ZIP-Datei liegt danach unter `dist/KESt-Tool-Portable-Windows.zip`. Entpacken und `KESt-Tool.exe` starten. Die Daten liegen im Unterordner `Daten` neben der EXE. Für Schreibzugriff nicht unter `C:\Program Files` entpacken.

**Hinweis:** Der Build ist noch nicht auf Windows validiert. PyInstaller-Abhängigkeiten müssen gegebenenfalls ergänzt werden. Windows SmartScreen kann bei nicht signierten EXE-Dateien warnen. Datenordner und ZIP nicht öffentlich freigeben. Zum Beenden das Programmfenster schließen bzw. den Prozess beenden.

Docker- und Windows-Version verwenden **getrennte Datenbestände**. Die SQLite-Datenbank nicht gleichzeitig von beiden Instanzen öffnen; für einen Datenaustausch ist ein kontrollierter Backup-/Restore-Prozess erforderlich.
