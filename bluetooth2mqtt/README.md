# bluetooth2mqtt

Bluetooth-LE-Bridge nach dem Vorbild von zigbee2mqtt, derzeit mit Treiber für
Eurotronic / Euronics **Comet Blue** Heizkörperthermostate.

- Geräte per Scan anlernen, umbenennen, entfernen – über Web-Oberfläche oder MQTT
- Werte alle 10 Minuten auslesen, Solltemperatur und Einstellungen setzen
- Uhr der Thermostate wird täglich gestellt
- läuft als Docker-Container

## Voraussetzungen auf dem Server (DietPi)

1. **Bluetooth aktiv:** `dietpi-config` → Advanced Options → Bluetooth einschalten.
   Prüfen mit `bluetoothctl list` – es muss ein Controller erscheinen.
2. **Docker + Docker Compose:** über `dietpi-software` installieren.
3. **MQTT-Broker:** Mosquitto (über `dietpi-software` oder als Container, siehe unten).

Der Container nutzt den Bluetooth-Dienst (BlueZ) des Servers über D-Bus.
Der Bluetooth-Dienst muss also auf dem Server selbst laufen.

## Start

```bash
# Ordner bluetooth2mqtt auf den Server kopieren, dann:
cd bluetooth2mqtt
docker compose up -d --build
docker compose logs -f
```

Beim ersten Start wird `data/configuration.json` angelegt. Läuft MQTT nicht auf demselben
Server oder mit Passwort: dort eintragen und `docker compose restart`.

Web-Oberfläche: **http://<server-ip>:8099**

## Thermostate anlernen

Handy-App vorher schließen – die Thermostate erlauben nur eine Verbindung.

1. Web-Oberfläche → **Anlernen** → *Suche starten*
2. Bei jedem gefundenen „Comet Blue“ einen Namen eintragen (z. B. `wohnzimmer`), PIN `0`
   lassen, falls du sie in der App nie geändert hast → *Hinzufügen*
3. Die Bridge verbindet sich einmal und prüft die PIN. Danach erscheint das Gerät unter **Geräte**.

Erkennst du nicht, welches Thermostat welches ist: das mit dem stärksten Signal ist dem
Server am nächsten. Nach dem Anlernen zeigt jede Karte die Adresse; umbenennen geht jederzeit.

## configuration.json

```json
{
  "mqtt": { "server": "localhost", "port": 1883, "user": "", "password": "",
            "base_topic": "bluetooth2mqtt", "client_id": "bluetooth2mqtt" },
  "frontend": { "enabled": true, "host": "0.0.0.0", "port": 8099, "auth_token": "" },
  "bluetooth": { "adapter": "hci0", "poll_interval": 600, "sync_time_daily": true }
}
```

- `auth_token`: wenn gesetzt, fragt die Web-Oberfläche einmal danach (Schutz im Heimnetz).
- `poll_interval`: Sekunden zwischen zwei Abfragen. Nicht unter 300 – jede Verbindung kostet Batterie.

`data/devices.json` verwaltet die Bridge selbst (wie bei zigbee2mqtt).

## MQTT-API

| Topic | Inhalt |
|---|---|
| `bluetooth2mqtt/<name>` | Zustand als JSON (retained) |
| `bluetooth2mqtt/<name>/availability` | `{"state":"online"}` / `{"state":"offline"}` |
| `bluetooth2mqtt/<name>/set` | `21` oder `{"comfort_temperature":21,"eco_temperature":17}` |
| `bluetooth2mqtt/<name>/set/<feld>` | einzelner Wert, z. B. `.../set/eco_temperature` → `16` |
| `bluetooth2mqtt/<name>/get` | sofort auslesen |
| `bluetooth2mqtt/bridge/state` | `{"state":"online"}` / `offline` (Last Will) |
| `bluetooth2mqtt/bridge/devices` | alle angelernten Geräte |
| `bluetooth2mqtt/bridge/event` | `device_added`, `device_removed`, `device_renamed`, `scan_started`, `scan_finished` |
| `bluetooth2mqtt/bridge/logging` | Fehlermeldungen (z. B. ungültige Werte) |

### Anfragen an die Bridge

Senden an `bluetooth2mqtt/bridge/request/<befehl>`, Antwort kommt auf
`bluetooth2mqtt/bridge/response/<befehl>` mit `"status": "ok"` oder `"error"`.
Ein mitgeschicktes `"transaction"` wird in der Antwort zurückgegeben.

| Befehl | Payload |
|---|---|
| `scan` | `{"time": 15}` |
| `device/add` | `{"address": "E0:E5:CF:12:34:56", "friendly_name": "wohnzimmer", "pin": 0}` |
| `device/remove` | `{"id": "wohnzimmer"}` |
| `device/rename` | `{"from": "wohnzimmer", "to": "stube"}` |
| `device/options` | `{"id": "wohnzimmer", "options": {"pin": 123456}}` |

### Werte eines Comet Blue

| Feld | Bedeutung | setzbar |
|---|---|---|
| `local_temperature` | gemessene Raumtemperatur | |
| `current_heating_setpoint` | aktuelle Solltemperatur, 7,5–28,5 °C | ✔ |
| `comfort_temperature` | Komforttemperatur | ✔ |
| `eco_temperature` | Absenktemperatur | ✔ |
| `local_temperature_calibration` | Offset, −5 … +5 °C | ✔ |
| `window_open_detection`, `window_open_minutes` | Fenster-auf-Erkennung (Rohwerte) | ✔ |
| `battery` | Batterie in %, `null` wenn unbekannt | |
| `flags` | Status-Bits als Hex (Rohwert) | |
| `last_seen` | Zeitpunkt der letzten Verbindung | |

## Node-RED

Menü → Import → `nodered-flow.json` → Deploy. Der Flow speichert alle Werte im
Flow-Kontext unter `heizung.<name>` und schickt Zeitplan-Befehle automatisch an alle
Geräte, die sich gemeldet haben. Nur die Beispiel-Buttons für einzelne Räume musst du an
deine Gerätenamen anpassen.

## Hinweise

- **Wochenprogramm im Thermostat:** überschreibt eine gesetzte Solltemperatur beim nächsten
  Schaltpunkt. Entweder das Programm in der App leeren und komplett über Node-RED planen,
  oder nur Komfort-/Absenktemperatur setzen.
- **Reichweite:** Ist ein Gerät oft `offline`, steht der Server zu weit weg. Ein USB-Bluetooth-Stick
  an einem Verlängerungskabel hilft oft schon.
- **Testmodus ohne Bluetooth:** `docker compose run --rm bluetooth2mqtt python bluetooth2mqtt.py --data /app/data --mock`
  simuliert drei Thermostate (die dritte hat PIN 123456).

## Mosquitto als Container (falls noch keiner läuft)

In `docker-compose.yml` den `mosquitto`-Block einkommentieren und anlegen:

```bash
mkdir -p mosquitto/config
printf 'listener 1883\nallow_anonymous true\npersistence true\npersistence_location /mosquitto/data/\n' > mosquitto/config/mosquitto.conf
docker compose up -d
```
