# Architektur ab Version 2.0.0

Die reguläre Oberfläche verwendet jetzt React und FastAPI. Der Root-`Dockerfile` baut beide Teile.
Intern hört `kest-tool` auf Port **8000**; Caddy reicht `/steuer/` dorthin weiter.
Der neue Healthcheck ist **`/steuer/api/health`**. Streamlit-WebSocket-Einstellungen aus älteren
Anleitungen sind für diese Version nicht mehr nötig. Der Portal-Port 8080 und die Ablage `data/kest`
bleiben erhalten. Lokale Anpassungen der Portbindung in `compose.yaml` beim Aktualisieren erhalten.

Update im aktuellen Serverordner:

```bash
cd /root/Steuer-Tool
git status --short
git pull --ff-only origin main
export COMPOSE_PROJECT_NAME=kest
export COMPOSE_FILE=compose.yaml
bash scripts/update-server.sh
curl -f http://127.0.0.1:8080/steuer/api/health
```

Bei einem Git-Konflikt durch eine lokal angepasste Compose-Datei nicht mit `reset --hard` fortfahren.
Portanpassung erhalten und die neue Build-Konfiguration (Kontext `.`; kein Streamlit-Command) übernehmen.
Der Update-Befehl baut zuerst und sichert vor dem Umschalten die vorhandenen Daten. Ein separater
KI-Server wird weiterhin über die Einstellungen angebunden; kein zusätzliches Ollama-Overlay nötig.

Danach Browser mit Strg+F5 neu laden. [Architektur](docs/ARCHITEKTUR.md).

---

# KESt-Steuertool – Docker-Deployment ohne Anmeldung

**Status:** KESt-Steuertool ohne Login-Maske. Der Caddy-Proxy verwendet keine HTTP-Basic-Authentifizierung.

## Sicherheit und Erreichbarkeit

Die Anwendung verarbeitet vertrauliche Finanz- und Steuerdaten. Ohne Anmeldung darf sie **nicht ungeschützt ins Internet** gestellt werden. Standardmäßig bindet Docker den Portal-Port nur an `127.0.0.1` des Servers. Für entfernte Geräte wird ein SSH-Tunnel oder ein VPN empfohlen. Bei einem eigenen Nginx-Reverse-Proxy den Zugriff auf vertrauenswürdige Netze/VPN begrenzen und HTTPS verwenden.

## Einrichtung

```bash
git clone https://github.com/C3rb3rus2050/Steuer-Tool.git
cd Steuer-Tool
mkdir -p data/kest
sudo chown -R 10001:10001 data/kest
docker compose config -q
docker compose up -d --build
docker compose ps
```

Ein Passwort-Hash und die Variablen `PORTAL_USERNAME`/`PORTAL_PASSWORD_HASH` sind **nicht mehr erforderlich**. Eine vorhandene lokale `.env` mit diesen alten Variablen kann bereinigt werden.

Standardport: `PORTAL_PORT=8080`. Die Weboberfläche liegt unter `/steuer/`.

### Zugriff von Windows über SSH-Tunnel

```powershell
ssh -L 8080:127.0.0.1:8080 root@LXC-IP
```

Anschließend `http://127.0.0.1:8080/steuer/` öffnen.

### Direkter LAN-Zugriff (nur bewusst freigeben)

Wenn die Anwendung direkt im LAN erreichbar sein soll, muss die Portbindung `127.0.0.1:${PORTAL_PORT:-8080}:8080` in `compose.yaml` auf die gewünschte Server-IP geändert werden. Ohne Login können dann alle Geräte mit Netzwerkzugriff auf diesen Port Dokumente ansehen, importieren und ändern. Den Zugang über Firewall, VPN oder Reverse-Proxy-Regeln begrenzen. Für Zugriff über das öffentliche Internet ist diese Konfiguration **nicht geeignet**.

## Import und Datensicherung

Broker-PDFs und CSV-/Excel-Dateien werden manuell unter `/steuer/` importiert. Vor Updates den persistenten Ordner `data/kest` sichern. Docker Compose löscht vorhandene Daten nicht automatisch.

## Dauerhafte Einstellungen und Updates

Der KESt-Container läuft als Benutzer mit UID/GID `10001:10001`.
Bei bestehenden Installationen vor dem ersten Update die Container stoppen und
`sudo chown -R 10001:10001 data/kest` ausführen. Danach `docker compose up -d --build`.

Einstellungen werden in `data/kest/config/config.yaml` gespeichert und bei jedem
Start geladen. Optionale API-Schlüssel liegen in `data/kest/secrets/.env` mit
restriktiven Dateirechten. Diese Schlüssel sind bewusst **nicht Teil des ZIP-Backups**;
sie müssen auf einem neuen System erneut eingegeben werden. Alte Einstellungen und
Schlüssel aus der beschreibbaren Schicht eines bisherigen Containers vor dessen
Entfernen sichern bzw. im neuen Container erneut eingeben.

Die Wiederherstellung lässt den eingebundenen Datenordner bestehen. Vorherige Daten
liegen anschließend unter `data/kest/backups/vor_Wiederherstellung_*`.
Vorhandene Backup-Dateien und API-Schlüssel bleiben erhalten. Während der
Wiederherstellung darf keine andere Sitzung Änderungen vornehmen.

## Server aktualisieren

Im bestehenden Repository auf dem Linux-Server ausführen (als root oder mit Zugriff auf Docker und die Datenablage):

```bash
git pull --ff-only origin main
bash scripts/update-server.sh
```

Das Skript validiert Compose und baut zuerst das Image. Erst danach stoppt es die Container,
sichert `data/kest` einschließlich Datenbank, Konfiguration und Schlüsseln in ein privates
Archiv unter `../Steuer-Tool-Backups/` und startet das Deployment mit Gesundheitsprüfung.
Bei einem Fehler während der Sicherung werden die vorhandenen Container wieder gestartet.
Mit `KEST_BACKUP_DIR=/sicherer/pfad` lässt sich das Backup-Ziel ändern. Auf einem anderen
Volume eingebundene Daten erfordern eine passend angepasste Sicherung; dieses Skript gilt
für die unveränderte `compose.yaml` mit `./data/kest`.

Zusätzliche Kontrolle (Port gegebenenfalls an `PORTAL_PORT` anpassen):

```bash
curl --fail http://127.0.0.1:8080/steuer/api/health
docker compose logs --tail=80 kest-tool
```

Version 1.1.0 ergänzt automatisch Datenbankschema 4. Ältere Exporte werden nicht neu geschrieben.
Nach dem Update Steuerberechnung erneut öffnen, neue Prüfhinweise bearbeiten und benötigte
Exporte neu erzeugen. Taggleiche Bestandsänderungen benötigen gegebenenfalls eine tatsächliche
Ausführungsreihenfolge unter **Buchungen → Weitere Spalten anzeigen**.
