# Docker Compose im Proxmox-LXC – Entwicklungsstand

## Vorbereitung
Die Collector-Anmeldung läuft in einem sichtbaren Chromium-Browser innerhalb
des Containers. Über noVNC kann dieser Browser mit einem SSH-Tunnel bedient werden.
Zugangsdaten und 2FA werden ausschließlich auf der offiziellen Broker-Seite eingegeben.

```bash
git clone https://github.com/C3rb3rus2050/Docker.git
cd Docker
git checkout feature/lxc-docker-compose
mkdir -p data/kest data/collector data/browser-profiles secrets
chmod 700 secrets data/browser-profiles
# Starkes, eigenes VNC-Passwort eingeben (nicht in der Shell-History):
read -rsp 'VNC-Passwort: ' VNC_PASS; echo
printf '%s' "$VNC_PASS" > secrets/vnc_password
unset VNC_PASS
chmod 600 secrets/vnc_password
docker compose up -d --build
docker compose ps
```

## Zugriff
Ports 8501 (KESt), 8765 (Collector), 6080 (noVNC) sind **nur auf
127.0.0.1 des Docker-Hosts** gebunden. Vom eigenen PC einen SSH-Tunnel
zum LXC aufbauen:

```bash
ssh -L 8501:127.0.0.1:8501 -L 8765:127.0.0.1:8765 -L 6080:127.0.0.1:6080 USER@LXC-IP
```

Dann auf dem PC:
- KESt: http://127.0.0.1:8501
- Collector: http://127.0.0.1:8765
- Sichtbarer Browser: http://127.0.0.1:6080/vnc.html

Zuerst die Browseransicht öffnen, dann im Collector „Anmeldung starten“
klicken und die Anmeldung inklusive 2FA selbst durchführen. Die VNC-Verbindung
nutzt ein Passwort, aber **kein TLS**: daher ausschließlich über SSH-Tunnel,
nicht direkt über das Internet/LAN exponieren.

## Daten
- `data/collector`: PDF-Dokumente, SQLite, Logs und Berichte
- `data/browser-profiles`: **sensible** Browserprofile; nicht öffentlich freigeben
- `data/kest`: Steuerdatenbank und Exporte
- `secrets/vnc_password`: VNC-Passwort; niemals committen

Der Collector-Speicher ist im KESt-Container unter `/data/collector` nur lesbar.
Der Ordnerimport im KESt-Tool muss derzeit manuell angestoßen werden.

## Bekannte Grenzen
- Die Container wurden hier noch nicht gebaut oder gestartet.
- Die Browser-Selektoren sind nicht mit echten Brokerkonten validiert.
- Browserprofile können eine erneute 2FA verlangen.
- Eine automatische KESt-Übernahme und gemeinsame Oberfläche fehlen noch.
- Die Playwright-Version des Images und des Python-Pakets muss vor
  Produktivbetrieb fest gepinnt und geprüft werden.
- Keine öffentliche Exponierung der Weboberflächen ohne zusätzliche Authentifizierung.
