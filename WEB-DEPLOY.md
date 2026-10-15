# KESt-Steuertool – Docker-Deployment

**Status:** KESt-Steuertool mit Zugangsschutz.

## Voraussetzungen

Docker Compose im Linux-LXC. Die Ports sind standardmäßig nur an localhost gebunden.
Erreichbarkeit von einem anderen Gerät per SSH-Tunnel oder vorgeschaltetem authentifiziertem HTTPS-Proxy.

## Einrichtung

```bash
git clone https://github.com/C3rb3rus2050/Docker.git
cd Docker
mkdir -p data/kest
# Passwort-Hash erzeugen (Passwort wird interaktiv abgefragt):
docker run --rm -it caddy:2.9-alpine caddy hash-password
```

Den ausgegebenen Hash in eine lokale `.env`-Datei eintragen.
**Wichtig:** Den bcrypt-Hash in der `.env` in **einfache Anführungszeichen** setzen. Dadurch bleiben die Dollarzeichen im Hash erhalten. Keine doppelten Dollarzeichen im `.env`-Wert verwenden.

```dotenv
PORTAL_USERNAME=admin
PORTAL_PASSWORD_HASH='<BCRYPT_HASH_UNVERAENDERT>'
PORTAL_PORT=8080
```

```bash
docker compose config -q
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```

Von Windows aus per SSH-Tunnel:

```powershell
ssh -L 8080:127.0.0.1:8080 root@LXC-IP
```

Danach: http://127.0.0.1:8080

Für direkten LAN-Zugriff muss die Portbindung in `compose.yaml` bewusst geändert und
HTTPS mit Zugriffsschutz konfiguriert werden. **HTTP Basic Auth ohne TLS nur über
einen SSH-Tunnel benutzen.**

## Import

Broker-PDFs und CSV-/Excel-Dateien werden manuell heruntergeladen und im KESt-Tool unter `/steuer/` importiert. Es gibt keinen Broker-Collector mehr.

Bestehende Dateien aus früheren Installationen werden durch Docker Compose nicht automatisch gelöscht. Prüfen Sie Sicherungskopien vor manueller Bereinigung.
