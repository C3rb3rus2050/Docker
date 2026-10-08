# Vaillant-ESP – überarbeitete Firmware

## Was neu ist

- **Taster und Dashboard synchron:** Soll (10–28 °C, 0,5er-Schritte), Vorlaufstufe (1–9) und
  Heizung AN/AUS verwaltet der ESP. Ein Druck auf einen Taster ändert den Wert sofort im
  Node-RED-Dashboard, eine Änderung im Dashboard sofort am ESP. Die Werte stehen im Flash und
  überstehen Neustarts.
- **Automatikbetrieb sperrt die Bedienung:** Ist „Automatik Betrieb“ an, sind Soll und Vorlaufstufe
  im Dashboard ausgegraut und die vier Temp-/Vorlauf-Taster am ESP gesperrt (Display: „AUTO –
  Taster gesperrt“, unten rechts ein „A“). „Set:“ zeigt dann das berechnete Ziel. Heizung AN/AUS
  bleibt immer bedienbar. Im Notbetrieb gilt keine Sperre. Schaltet man auf Handbetrieb zurück,
  erscheinen wieder die zuletzt von Hand eingestellten Werte.
- **Sicherer Start:** Nach einem Neustart bleibt die Therme aus, bis Node-RED sich meldet
  (höchstens 3 Minuten). Früher startete sie sofort mit Stufe 8 (~75 °C). Als Lebenszeichen
  zählt nur `Reboot = 1` vom Watchdog-Flow; die gespeicherten (retained) Werte `heaterOn/Off`
  und `Vorlauftemp` übernimmt der ESP, sie halten ihn aber nicht in der Fernsteuerung.
- **Notbetrieb:** 15 Minuten ohne Lebenszeichen von Node-RED → der ESP regelt selbst nach dem
  Thermistor an A0. Beim Wechsel hebt er Soll und Vorlaufstufe einmalig auf mindestens 18 °C bzw.
  Stufe 4 an; danach sind beide mit den Tastern frei einstellbar (10–28 °C, Stufe 1–9).
  Ist der Fühler gestört, heizt er durchgehend weiter (die Heizkörper-Thermostate begrenzen).
  „Heizung AUS“ gilt auch im Notbetrieb, bis auf den Frostschutz: unter `FALLBACK_FROST_TEMP`
  (12 °C) heizt der ESP trotzdem, denn das AUS kann auch vom Zeitplan stammen. Ohne Fühler gibt
  es bei „Heizung AUS“ keinen Frostschutz. Im Display steht „NOT“ und die gemessene Temperatur.
- **Nichts blockiert:** Ohne WLAN, MQTT, Internet, Display oder RTC läuft der ESP trotzdem weiter.
  Kein Selbst-Neustart mehr, wenn Node-RED schweigt.
- **Zeit:** Sommer-/Winterzeit automatisch.
- **Status:** `home/vaillant/esp1/status` (JSON) mit Betriebsart, Stufe, Fühlerwert und ADC-Rohwert.

## Vor dem Flashen anpassen

1. `include/secrets_example.h` nach `include/secrets.h` kopieren und WLAN-Daten eintragen.
   Braucht dein Broker eine Anmeldung, `#define MQTT_USE_AUTH` einkommentieren.
2. In `include/config.h` den Thermistor prüfen:
   - `NTC_SERIES_R` = Wert des zweiten Widerstands im Spannungsteiler
   - `NTC_TO_GND` = `true`, wenn der NTC zwischen A0 und GND liegt
   - `ADC_FULLSCALE_V` = 3.2 bei Wemos D1 mini / NodeMCU, 1.0 bei nacktem ESP-12
   - `NTC_BETA` laut Datenblatt (oft 3950)
3. In `platformio.ini` das Board eintragen (ist auf `nodemcuv2` gesetzt).

Nach dem Flashen den Wert `room_temp` im Status-Topic mit einem Thermometer vergleichen und
die Abweichung als `TEMP_OFFSET` eintragen. `adc` zeigt den Rohwert, falls etwas nicht stimmt.

## Node-RED

`node-red/esp-sync-import.json` importieren (Menü ☰ → Import). Node-RED meldet, dass einige
Knoten schon existieren → **„Ersetzen“** wählen. Danach Deploy.

Was der Import macht:
- neuer Tab **ESP Sync** mit der Synchronisierung in beide Richtungen
- im Tab *Heizung* drei Verbindungen von „Temperatur Soll“, „Vorlauftemperatur“ und
  „Heizung AN/AUS“ zum neuen Tab, plus zwei Eingänge zurück
- die alten Taster-Eingänge (`TempUp`, `TempDown`, `VorlaufUp`, `VorlaufDown`, `heater`) werden
  deaktiviert, nicht gelöscht
- `heaterOn/Off` und `Vorlauftemp` werden mit **retain** gesendet, damit der ESP nach einem
  Neustart sofort den aktuellen Zustand bekommt
- der Test-Inject „Außentemperatur (Test)“ mit −1 °C wird deaktiviert
- die Start-Injects im Tab *Heizung* für Soll (21 °C), Vorlaufstufe (8) und Heizung AN/AUS werden
  deaktiviert. Der ESP ist führend und meldet seine Werte beim Start von Node-RED selbst; die
  Injects hätten sie bei jedem Neustart überschrieben. Bis der ESP geflasht ist, startet Node-RED
  deshalb ohne diese Vorgaben (Soll 20 °C, Heizung freigegeben).
- die Schalter „Heizung AN/AUS“ und „Automatik Betrieb“ zeigen danach richtig herum an: AN
  bedeutet Heizung freigegeben bzw. Automatik aktiv. Bisher waren beide verdreht, die Regelung
  dahinter bleibt unverändert.
- `build_import.py` erzeugt die Importdatei aus einem neuen Export, falls du vorher etwas änderst

**Reihenfolge:** zuerst Node-RED importieren, dann den ESP flashen.

Hinweis: Im Automatikbetrieb zeigt „Temperatur Soll“ das von der Einzelraumregelung berechnete
Ziel. Diesen Wert übernimmt der ESP genauso wie eine Eingabe. Ein Tastendruck am ESP verhält
sich wie eine Änderung im Dashboard: im Automatikbetrieb gilt er bis zur nächsten automatischen
Berechnung.
