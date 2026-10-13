# Wertpapier-Steuer-Werkzeuge (privat, lokal, Windows 11)

Dieses Repository enthält zwei **eigenständige** Projekte. Jedes hat eigenen Code, eigene Abhängigkeiten, eigene
Tests sowie eigene Installations- und Startskripte. Keines benötigt das andere.

| Ordner | Projekt | Zweck | Start |
|---|---|---|---|
| [`kest-tool/`](kest-tool) | **KESt-Tool** | Österreichische Kapitalertragsteuer: Import (CSV/Excel/PDF/OeKB), nachvollziehbare Steuerberechnung, Excel-Export mit 11 Blättern, E 1kv-Arbeitshilfe | `kest-tool\install.bat`, dann `kest-tool\start.bat` |
| [`broker-document-collector/`](broker-document-collector) | **Broker Document Collector** | Automatischer Download aller Dokumente aus Trade Republic und Scalable Capital (Anmeldung selbst im Browser) | `broker-document-collector\install.bat`, dann `broker-document-collector\start.bat` |

Optionales Zusammenspiel: Den Ausgabeordner des Collectors können Sie im KESt-Tool über **Import → Ordner einlesen**
übernehmen.

Details stehen in den README-Dateien der beiden Ordner.
