# Hier weiterarbeiten – Steuer-Tool

## Architekturwechsel auf 2.0.0

Die reguläre Anwendung wurde auf React/TypeScript/Vite und FastAPI umgebaut, analog zum Mealplanner.
Siehe `docs/ARCHITEKTUR.md`. SQLite-Datenbank und Datenvolume bleiben bestehen. Root-Dockerfile,
Compose-Buildkontext `.`, interner Port 8000, Healthcheck `/steuer/api/health`.
Die nachfolgenden Angaben zu Version 1.5.0 und Streamlit-WebSockets sind historischer Kontext.
Die neue Oberfläche benötigt keine dauerhafte WebSocket-Verbindung. Der Domainzugang auf dem privaten
Server muss nach dem Deployment weiterhin geprüft werden. Serverordner `/root/Steuer-Tool`, Compose-Projekt `kest`.
Kein zusätzliches Ollama auf dem Steuer-Server starten; vorhandenen KI-Server über Einstellungen anbinden.

Stand: 16.10.2026 · Anwendungsversion **1.5.0**

## Sofortiger Einstieg

Repository: <https://github.com/C3rb3rus2050/Steuer-Tool>

Alle bisherigen Anwendungsänderungen sind in **main** enthalten. Letzter geprüfter
Anwendungscommit vor dieser Übergabe:
[`27d9958`](https://github.com/C3rb3rus2050/Steuer-Tool/commit/27d99581a3a9c5a32be7d946e043913f7de9b78f).
Die zugehörigen GitHub-Prüfungen waren erfolgreich. Diese Übergabe ändert keinen Anwendungscode.

**Als Nächstes das Ladeproblem über die Domain untersuchen.** Danach den bereits vorhandenen,
separaten KI-Server anbinden. Seine Adresse und API sind noch nicht bekannt.

Vorschlag für den Einstieg in einen neuen Chat:

> Lies WEITERARBEITEN.md und prüfe den aktuellen main-Stand. Setze beim Domain-/WebSocket-Problem
> fort. Der KI-Dienst soll auf meinem vorhandenen separaten KI-Server laufen. Behalte die
> kompakte Oberfläche und die direkte Bearbeitung neben dem Original bei.

## Was bereits umgesetzt ist

- Streamlit-Anwendung mit SQLite und Docker Compose; Portal/Reverse-Proxy über Caddy.
- Gemeinsamer Import von PDF, ZIP, CSV und Excel; Brokerregeln und optionale lokale Tesseract-OCR.
- Erweiterte Erkennung anhand öffentlicher Trade-Republic-, Scalable- und Baader-Beispieltexte.
- **Belege & Prüfung:** Original links, Eingabefelder rechts; direkt speichern, ohne ein neues
  Fenster oder einen separaten Beleg-Auswahldialog. Korrekturen und manuelle Übernahmen mit Prüfungen und Protokoll.
- **Wertpapiere:** derselbe Kartenablauf. Links offene Angaben, Quellen und zugehörige Belege;
  rechts Stammdaten, steuerliche Einstufung, Quellen und Meldefondsstatus.
- Jeweils **ein Eintrag pro Ansicht** mit **Zurück / Weiter**, offene Einträge zuerst.
  Änderungen vor dem Weiterblättern speichern. Nach abgeschlossener Wertpapierprüfung erscheint
  der nächste offene Eintrag. Optionale Felder lassen sich auch leeren.
- Oberfläche im OrangeHRM-Stil, kompakte Seitenleiste, **keine Menüsuche**.
- **Hell / Dunkel / System** über das Menü **⋮** oben rechts. System folgt der Gerätevorgabe.
  Die Portal-Startseite hat eine separate, im Browser gespeicherte Auswahl.
- Optionale KI-Vorschläge mit Quellenstellen, expliziter Feldauswahl und Übernahme ins Prüfformular.
  Kein automatisches Buchen durch KI und keine steuerliche Einstufung durch das Modell.

## Benutzerwünsche, die erhalten bleiben sollen

- Wenig Scrollen, kompakte Eingaben und möglichst wenige Bedienungsschritte.
- Direkt am aktuellen Beleg bzw. Wertpapier bearbeiten; keine unnötigen Fensterwechsel.
- Keine Menüsuche wieder einbauen.
- Einen vorhandenen **separaten KI-Server** verwenden. Kein zusätzliches Ollama auf dem Steuer-Server starten.
- Änderungen vollständig umsetzen, prüfen und nach GitHub pushen; passende Serverbefehle liefern.

## Server und Update

Der aktuelle Repository-Ordner auf dem Linux-Server ist **/root/Steuer-Tool**.
Früher wurde **/root/kest** mit dem Repository **Docker.git** verwendet; das ist nicht mehr
das beabsichtigte Arbeitsverzeichnis. Compose-Projektname bleibt **kest**.

Der Benutzer hatte eine lokal angepasste **compose.yaml**, insbesondere für die Portbindung.
Diese Anpassung nicht blind überschreiben oder mit einem Hard-Reset entfernen.
Der tatsächliche zuletzt installierte Servercommit muss bei Bedarf geprüft werden;
ein erfolgreicher Git-Push ist noch kein Nachweis eines Serverupdates.

```bash
cd /root/Steuer-Tool
git remote -v
git status --short
git log -1 --oneline
git pull --ff-only origin main

export COMPOSE_PROJECT_NAME=kest
export COMPOSE_FILE=compose.yaml
bash scripts/update-server.sh
docker compose ps
```

Das Skript baut vor dem Stoppen, sichert die vorhandene Ablage **data/kest** einschließlich
Konfiguration und Secrets nach **../Steuer-Tool-Backups** und startet mit Gesundheitsprüfung.
Danach Browser mit **Strg+F5** neu laden. Für diese reine Markdown-Übergabe ist kein Neubau nötig.

**compose.ai.yaml nicht zuschalten:** Dieses optionale Overlay würde einen zusätzlichen
Ollama-Container auf dem Steuer-Server einrichten. Das entspricht nicht dem Benutzerwunsch.
Ein früher eventuell gestarteter Container wird durch Weglassen des Overlays nicht automatisch gestoppt;
den tatsächlichen Containerbestand gegebenenfalls prüfen. Modelle oder Nutzdaten nicht ungefragt löschen.

## Offenes Problem: Domain lädt nur die Startseite

Gemeldetes Verhalten:

- Über direkten IP-Zugriff ist die Anwendung laut Benutzer erreichbar.
- Über **https://steuer.c3rb3rus.com/** lädt die statische Portal-Startseite.
- Unter **/steuer/** bleibt die Anwendung bei den grauen Ladeplatzhaltern stehen.

**Noch keine gesicherte Ursache und noch kein Proxy-Fix umgesetzt.** Vermutung:
WebSocket-Weiterleitung, Origin-Prüfung oder Pfadbehandlung im vorgeschalteten Proxy.
Welcher Proxy davor läuft (Nginx Proxy Manager, Cloudflare Tunnel usw.), wurde noch nicht beantwortet.

Die vorhandene Route in **portal/Caddyfile** reicht **/steuer/** unverändert an **kest-tool:8501**
weiter. Der Container startet Streamlit mit **--server.baseUrlPath=steuer**.
Der externe Proxy muss den Pfad erhalten. Nicht vorsorglich CORS oder XSRF-Schutz abschalten.

Nächste Diagnose:

1. Tatsächlichen vorgeschalteten Proxy und seine Konfiguration feststellen.
2. Im Browser **F12 → Netzwerk → WS** öffnen und die Seite neu laden.
3. Verbindung zu **wss://steuer.c3rb3rus.com/steuer/_stcore/stream** prüfen:
   erwartet wird **101 Switching Protocols**. **403** deutet auf Origin-/Zugriffsschutz,
   **404** auf Routing/Pfadbehandlung, **502/504** auf ein nicht erreichbares Backend hin.
4. Domain- und direkten IP-Zugriff sowie Proxy-/Containerlogs vergleichen.
   Ein erfolgreicher HTTP-Healthcheck allein beweist keine funktionierende WebSocket-Verbindung.

Falls Nginx Proxy Manager verwendet wird: WebSocket-Unterstützung und den richtigen HTTP-Upstream
zum Portal auf Port **8080** prüfen. Noch nicht als tatsächlich verwendetes Produkt bestätigt.

## Separaten KI-Server anbinden

Die bisherige Implementierung unterstützt die **Ollama-API /api/generate**.
Unter **Einstellungen → Dokumentenerkennung → Lokale KI** sind Basisadresse, Modellname und Aktivierung
konfigurierbar. „Lokal“ bedeutet hier selbst betriebener Dienst; die Adresse darf auf einen anderen Rechner zeigen.

Noch benötigt: erreichbare Adresse aus dem Steuer-Container, verwendeter Dienst/API, Modellname
und eventuell erforderliche Authentifizierung. Bei vLLM, LM Studio oder einer anderen API zuerst
einen passenden Adapter implementieren; die Ollama-Anbindung ist nicht automatisch kompatibel.
Keine Zugangsdaten in Markdown oder Git eintragen.

KI-Vorschläge sind nur Textextraktion, keine direkte Bildanalyse. Ohne Text wird OCR versucht.
Textstellen und Rohwerte werden geprüft, ebenso unterstützte Zahlen-, Datums- und ISIN-Angaben.
Eine passende Textstelle beweist noch nicht die fachlich richtige Zuordnung von Brutto/Netto oder Quellensteuer.
Die Modell-Erkennungsqualität auf privaten Originalbelegen wurde nicht gemessen.

## Prüfung und Grenzen

- Letzter vollständiger Lauf: **314 bestanden, 1 übersprungen** (lokal fehlendes Tesseract; im Docker-Image enthalten).
- Nach den abschließenden Layout-/Navigationsänderungen: **24 relevante Tests bestanden**.
- Karten, Navigation, Hell/Dunkel/System und Formulare wurden zusätzlich im Browser mit Demodaten geprüft.
- Die echten PDFs des Benutzers liegen auf seinem Server, nicht lokal vor. Keine Behauptung,
  dass sämtliche privaten Belege bereits korrekt erkannt oder verarbeitet seien.
- Steuerliche Freigaben und Einschränkungen jahresbezogen in **kest-tool/docs/STEUERREGELN.md**
  und den weiteren Fachunterlagen prüfen. Bestandene Softwaretests sind keine steuerrechtliche Verifikation.

```bash
cd kest-tool
python -m pytest -q
```

## Wichtige Dateien

| Bereich | Pfad |
| --- | --- |
| Anwendung und Navigation | kest-tool/app.py |
| Gemeinsames Design | kest-tool/src/kest_tool/ui/admin_theme.py und admin_theme.css |
| Native Darstellung | kest-tool/.streamlit/config.toml |
| Belegkarten | kest-tool/src/kest_tool/ui/document_review.py |
| Gemeinsames Zurück/Weiter | kest-tool/src/kest_tool/ui/review_pager.py |
| Wertpapierkarten | kest-tool/src/kest_tool/ui/security_review.py |
| Validiertes Speichern der Wertpapierprüfung | kest-tool/src/kest_tool/security_review.py |
| Belegübernahme | kest-tool/src/kest_tool/document_review.py |
| PDF-Regeln und OCR | kest-tool/src/kest_tool/importers/pdf_importer.py |
| Ollama-Vorschläge | kest-tool/src/kest_tool/importers/assisted.py |
| KI-Bedienung | kest-tool/src/kest_tool/ui/assisted_review.py |
| Portal und interner Proxy | portal/index.html und portal/Caddyfile |
| Betrieb | compose.yaml, scripts/update-server.sh, WEB-DEPLOY.md |

Weitere Ablaufbeschreibungen: **kest-tool/docs/WERTPAPIERPRUEFUNG.md**,
**DIREKTE-BELEGPRUEFUNG.md** und **LOKALE-KI.md**. Die dort dokumentierte optionale
Ollama-Installation auf dem Steuer-Server ist für diesen Benutzer nicht das gewünschte Deployment.

Bei einer Fortsetzung zuerst **origin/main** aktualisieren und vergleichen. Die bisherigen lokalen
Arbeitsbranches enthalten teilweise inhaltlich gleiche Commits mit anderer SHA als die über den
GitHub-Connector veröffentlichten Commits. Diese Branches nicht pauschal erneut zusammenführen.
