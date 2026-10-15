# KESt-Steuertool – Docker-Deployment ohne Anmeldung

**Status:** KESt-Steuertool ohne Login-Maske. Der Caddy-Proxy verwendet keine HTTP-Basic-Authentifizierung.

## Sicherheit und Erreichbarkeit

Die Anwendung verarbeitet vertrauliche Finanz- und Steuerdaten. Ohne Anmeldung darf sie **nicht ungeschützt ins Internet** gestellt werden. Standardmäßig bindet Docker den Portal-Port nur an `127.0.0.1` des Servers. Für entfernte Geräte wird ein SSH-Tunnel oder ein VPN empfohlen. Bei einem eigenen Nginx-Reverse-Proxy den Zugriff auf vertrauenswürdige Netze/VPN begrenzen und HTTPS verwenden.

## Einrichtung

```bash
git clone https://github.com/C3rb3rus2050/Docker.git
cd Docker
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
