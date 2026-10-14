# Docker Compose im Proxmox-LXC – erste Entwicklungsfassung

Die beiden bestehenden Anwendungen werden getrennt gebaut und mit persistenten Ordnern betrieben.

## Start

```bash
git clone https://github.com/C3rb3rus2050/Docker.git
cd Docker
git checkout feature/lxc-docker-compose
mkdir -p data/kest data/collector data/browser-profiles
docker compose up -d --build
docker compose ps
docker compose logs -f
```

Die Weboberflächen sind absichtlich **nur auf 127.0.0.1 des Docker-Hosts** gebunden:
KESt auf Port 8501, Collector auf Port 8765. Für den Zugriff von einem anderen Rechner
einen authentifizierten Reverse Proxy mit HTTPS oder einen SSH-Tunnel einsetzen.
**Nicht ungeschützt im LAN oder Internet veröffentlichen.**

## Noch nicht fertig: Broker-Anmeldung

Der Collector setzt aktuell einen **sichtbaren lokalen Chromium-Browser** voraus.
Im Linux-Container fehlt ein Displayserver und damit eine interaktive Login-Möglichkeit.
Die Compose-Datei ist deshalb zunächst eine **Entwicklungsgrundlage, keine funktionierende
End-to-End-Broker-Synchronisierung**. Ein sicherer Remote-Browser mit manueller 2FA
muss vor einem Live-Test ergänzt werden. Keine Broker-Passwörter in Umgebungsvariablen
oder Compose-Dateien speichern.

Die Playwright-Image-Version muss mit der installierten Playwright-Python-Version
übereinstimmen. Vor produktivem Einsatz Versionen fixieren und den Build testen.

## Datenspeicher

- `data/collector`: Dokumente, SQLite-Datenbank und Berichte des Collectors
- `data/browser-profiles`: Browserprofile, **sensibel**; nur für berechtigte Nutzer
- `data/kest`: KESt-Datenbank, Importe und Exporte

Der Collector-Speicher ist im KESt-Container nur lesbar unter `/data/collector`.
Das KESt-Tool importiert Dateien bisher **nicht automatisch** aus diesem Ordner.
Dazu muss in der Oberfläche der Ordnerimport verwendet werden.

## Einschränkungen

- Noch kein authentifiziertes gemeinsames Dashboard
- Noch keine zuverlässige Remote-Browser-Anmeldung
- Noch kein Live-Test mit Trade Republic oder Scalable Capital
- Keine automatische KESt-Übernahme
- Keine Bestätigung, dass die Collector-Selektoren auf aktuellen Broker-Webseiten funktionieren
