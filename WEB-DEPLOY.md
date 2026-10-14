# Web-only Deployment ohne VNC

**Status:** Ein gemeinsames Webportal mit Zugangsschutz. Kein VNC, kein noVNC und kein Desktopserver.

## Voraussetzungen

Docker Compose im Linux-LXC. Die Ports sind standardmäßig nur an localhost gebunden.
Erreichbarkeit von einem anderen Gerät per SSH-Tunnel oder vorgeschaltetem authentifiziertem HTTPS-Proxy.

## Einrichtung

```bash
git clone https://github.com/C3rb3rus2050/Docker.git
cd Docker
mkdir -p data/kest data/collector data/browser-profiles
chmod 700 data/browser-profiles
# Passwort-Hash erzeugen (Passwort wird interaktiv abgefragt):
docker run --rm -it caddy:2.9-alpine caddy hash-password
```

Den ausgegebenen Hash in eine lokale `.env`-Datei eintragen.
**Wichtig:** Dollarzeichen im bcrypt-Hash für Docker Compose als `$$` escapen,
damit Compose diese nicht als Variablen interpretiert.

```dotenv
PORTAL_USERNAME=admin
PORTAL_PASSWORD_HASH=<BCRYPT_HASH_MIT_DOPPELTEN_DOLLARZEICHEN>
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

## Grenzen

Der Collector benutzt bisher Playwright mit persistenten Chromium-Profilen.
Im Web-only-Container läuft Chromium headless; bestehende gültige Sitzungen können
gegebenenfalls weiterverwendet werden. Eine neue Anmeldung mit 2FA kann **nicht**
über das Webportal abgeschlossen werden. Die Login-Schaltfläche wird deaktiviert.
Das ist eine bewusst dokumentierte Funktionseinschränkung und keine Umgehung von 2FA.
Ein vollständig webbasierter, sicherer Broker-Login muss separat entwickelt und mit
den realen Brokern validiert werden.

Broker-Downloads und Container-Build sind noch nicht live getestet.
