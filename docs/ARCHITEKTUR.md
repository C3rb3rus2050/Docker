# React und FastAPI – Version 2.0.0

Die reguläre Webanwendung verwendet dieselbe Grundarchitektur wie GrocyMealPlanner:

```text
Browser / installierbare PWA
    React 18 + TypeScript + Vite
            │ HTTP / JSON / Datei-Upload
            ▼
    /steuer/api – FastAPI + Uvicorn, Port 8000
            │ validierte Fachdienste
            ▼
    kest_tool – Repository, PDF/OCR, OeKB, Steuerregeln, Exporte
            │
    vorhandene SQLite-Datenbank und unveränderte Belegablage
```

## Datenkompatibilität

Die Datenbank bleibt unter `KEST_TOOL_HOME/database/kest_tool.db`. Docker verwendet weiterhin
`./data/kest:/data/kest`, UID/GID 10001 und den Dienstnamen `kest-tool`. Es findet keine
Konvertierung von Beträgen oder erneute Buchung alter Dokumente beim Start statt. Bestehende
Schemaergänzungen werden vom bisherigen SQLite-Modul angewendet. Eine zusätzliche ORM- oder
Alembic-Konvertierung ist für diesen Oberflächenwechsel nicht notwendig.

Die API verwendet `save_review`, `save_security_review`, `process_documents`, `process_tables`
und `compute`. Steuerlogik und jahresbezogene Freigaben werden durch den Architekturwechsel
nicht geändert. Der Quellcode der früheren Streamlit-Oberfläche bleibt für Regressionstests
und den bewussten lokalen Rückgriff vorhanden; Docker startet ausschließlich FastAPI/React.
Streamlit ist deshalb zunächst weiter eine Python-Abhängigkeit.

## Frontend

- `frontend/src/main.tsx`: Navigation, Steuerjahr, Hell/Dunkel/System, Erreichbarkeitsanzeige.
- `components.tsx`: kontrollierte Eingaben, Tabellen, paginierte Listen, Fehlerbehandlung.
- `review.tsx`: Belege, Wertpapiere und Buchungen mit Originalvorschau und direkten Formularen.
- `pages.tsx`: Import, Dashboard, Fonds, Depots, Berechnung, Export und Einstellungen.
- `api.ts`: gleicher Ursprung und `/steuer/api`, Fehler statt falscher Erfolgsmeldungen.
- Vite erzeugt statische Dateien in `frontend/dist`; Node läuft nur während des Builds.

Finanzielle Daten werden nicht vom Service Worker gecacht. Änderungen brauchen eine
Serververbindung. Die installierbare PWA ist kein Offline-Buchhaltungssystem. Formulare warnen
vor dem Verwerfen ungespeicherter Eingaben. KI-Felder werden ausdrücklich ausgewählt und
erst nach Originalvergleich über die normalen validierten Funktionen gespeichert.

## Backend

`backend/app/main.py` stellt die fachlichen HTTP-Endpunkte und die SPA bereit. Eingaben werden
mit Pydantic und den vorhandenen Fachmodellen geprüft. Beleg- und Buchungskorrekturen erhalten
Revisionskennungen, um Änderungen aus veralteten Tabs abzuweisen. Die SQLite-Anwendungsoperationen
laufen innerhalb eines pro Prozess geteilten Locks. Uvicorn wird mit einem Worker betrieben.

Dateien werden über Datenbank-IDs statt frei übergebener Dateipfade ausgeliefert. Originale
bleiben byte-identisch. ZIPs verwenden die begrenzte bestehende Entpackroutine. Schreibzugriffe
benötigen einen eigenen Request-Header; Cross-Site-Browserzugriffe werden abgewiesen und es gibt
keine freigiebige CORS-Konfiguration. Zugangsschutz und TLS am vorhandenen Reverse Proxy bleiben
erforderlich. Das API ist dieselbe private Anwendung, kein öffentlich freizugebender Dienst.

## Deployment und Proxy

Der mehrstufige Root-`Dockerfile` baut React mit Node 24 und kopiert die Dateien in das Python-Image.
FastAPI liefert die API und Oberfläche auf Port 8000 unter `/steuer/`. Caddy auf Port 8080 reicht
den Pfad unverändert durch. Die externe Domain und der Portal-Port können bestehen bleiben.
Es ist keine Streamlit-WebSocket-Verbindung und kein `/steuer/_stcore/stream` mehr erforderlich.
Externe Proxys müssen weiterhin das richtige Backend erreichen und `/steuer/` erhalten.

Healthcheck: `GET /steuer/api/health`; API-Dokumentation: `/steuer/docs`.

## Lokal entwickeln

```powershell
powershell -File scripts/setup.ps1
powershell -File scripts/start.ps1
```

Für Hot Reload in zwei Terminals aus dem Repository:

```powershell
$env:PYTHONPATH='kest-tool/src'
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

```powershell
cd frontend
npm run dev
```

Vite läuft unter `http://127.0.0.1:5173/steuer/` und leitet die API an Port 8000 weiter.

## Prüfen

```powershell
.\.venv\Scripts\python -m pytest -q
cd frontend
npm ci
npm test
npm run build
```

API-Integrationstests vergleichen die Berechnung mit der bestehenden Fachlogik und prüfen
Originaltreue, Dubletten, Revisionen, Jahreszuordnung, Exportdownloads und Sicherungen.
GitHub prüft Python auf Windows und Linux, den Frontend-Build und den vollständigen Docker-Start
einschließlich Tesseract-OCR. Private Serverdaten wurden damit nicht überprüft.
