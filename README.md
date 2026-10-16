# Österreichisches KESt-Steuertool

Dieses Repository enthält ausschließlich das **KESt-Steuertool** für österreichische Wertpapierdepots.

Seit **Version 2.0.0**: **React + TypeScript + Vite** als Frontend, **FastAPI** als Backend.
Beide werden gemeinsam über Docker ausgeliefert. Die vorhandene SQLite-Datenbank, Belegablage
und Steuerlogik bleiben erhalten. Details: [Architektur und lokale Entwicklung](docs/ARCHITEKTUR.md).

Windows: `powershell -File scripts/setup.ps1`, danach `powershell -File scripts/start.ps1`.
Die neue Oberfläche öffnet sich unter `http://127.0.0.1:8000/steuer/`.

- Import von manuell heruntergeladenen PDF-, ZIP-, CSV- und Excel-Dateien (Trade Republic, Scalable Capital und weitere Broker)
- Aktien, ETFs, REITs, BDCs, Melde- und Nichtmeldefonds mit Prüfhinweisen für steuerliche Sonderfälle
- OeKB-Fondsdaten, depotübergreifende Auswertung, Verlustausgleich und nachvollziehbare E 1kv-Arbeitshilfe
- Excel-, CSV- und PDF-Exporte mit Belegablage pro Steuerjahr

**Start unter Docker:** Siehe [WEB-DEPLOY.md](WEB-DEPLOY.md).

**Windows-Installation:** Siehe [kest-tool/README.md](kest-tool/README.md).

Das Tool ist eine Steuererklärungshilfe und ersetzt keine steuerliche Prüfung.
