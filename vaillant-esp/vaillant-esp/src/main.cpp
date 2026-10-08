/*****************************************************
 *  Vaillant-Steuerung – ESP8266
 *  -------------------------------------------------
 *  - Therme Ein/Aus und Vorlaufstufe (PWM an GPIO2) über MQTT von Node-RED
 *  - Einstellungen (Soll, Vorlaufstufe, Heizung Ein/Aus) verwaltet der ESP:
 *    Taster am ESP und Node-RED-Dashboard ändern dieselben Werte, beide Seiten
 *    sind immer synchron. Gespeichert im Flash, überstehen Neustarts.
 *  - Sicherer Start: Therme aus, bis Node-RED sich meldet
 *  - Notbetrieb: ohne Lebenszeichen von Node-RED regelt der ESP selbst
 *    nach dem Thermistor an A0 (oder heizt durchgehend, wenn der Fühler fehlt)
 *  - WLAN, MQTT und NTP blockieren nie; Display und RTC sind optional
 *  - Zeit mit automatischer Sommer-/Winterzeit, DS3231 als Gangreserve (UTC)
 *  - OTA-Update
 *
 *  MQTT (Basis home/vaillant/esp1/):
 *   Node-RED -> ESP
 *     heaterOn/Off (on/off)       Therme an/aus (Ergebnis der Regelung in Node-RED, retained)
 *     Vorlauftemp (1–9)           Vorlaufstufe (Ergebnis der Regelung in Node-RED, retained)
 *     Reboot (1 | 0)              1 = Node-RED lebt (einziges Lebenszeichen), 0 = Neustart
 *     cmd/setpoint (10–28)        Soll aus dem Dashboard
 *     cmd/vorlauf (1–9)           Vorlaufstufe aus dem Dashboard
 *     cmd/enabled (on/off)        Heizung AN/AUS aus dem Dashboard
 *     automode (on/off)           Automatikbetrieb in Node-RED: Soll und Vorlauf gesperrt
 *     targetTemp, current-temperature/get, HeizungStatus   nur Anzeige
 *   ESP -> Node-RED
 *     state/setpoint, state/vorlauf, state/enabled   aktuelle Einstellungen (retained)
 *     status (JSON, retained), online (1/0, Last Will), Watchdog ("Alive"),
 *     fallback/temperature
 *****************************************************/

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoOTA.h>
#include <RTClib.h>
#include <EEPROM.h>
#include <time.h>
#include <sys/time.h>
#include <coredecls.h>

#include "config.h"
#include "secrets.h"
#include "functions.h"

// ===================== Hardware ====================
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
RTC_DS3231 rtc;
WiFiClient espClient;
PubSubClient mqtt(espClient);

bool displayOk = false;
bool rtcOk = false;
bool otaStarted = false;

// ===================== Einstellungen ===============
struct Settings {
  uint32_t magic;
  float setpoint;     // Solltemperatur (manuell / Dashboard)
  uint8_t stage;      // Vorlaufstufe (manuell / Dashboard)
  uint8_t enabled;    // Heizung AN/AUS
};
const uint32_t SETTINGS_MAGIC = 0x56414931;  // "VAI1"
Settings settings;
bool settingsDirty = false;
unsigned long settingsChanged = 0;

// ===================== Vorgaben von Node-RED =======
bool remoteHeaterOn = false;
int  remoteStage = DEFAULT_STAGE;
bool remoteSeen = false;           // seit dem Start schon ein Lebenszeichen von Node-RED?
unsigned long lastRemote = 0;      // letztes Lebenszeichen von Node-RED (Reboot = 1)
String targetTempString  = "--";
String currentTempString = "--";
String statusString      = "--";
bool autoMode = false;              // Automatikbetrieb in Node-RED aktiv
unsigned long lockNoticeUntil = 0;  // Hinweis "gesperrt" im Display

// ===================== Betriebsart =================
enum Mode { MODE_STARTUP, MODE_REMOTE, MODE_FALLBACK };
Mode mode = MODE_STARTUP;
bool fallbackHeat = false;

// ===================== Fühler ======================
float roomTemp = NAN;
int   lastAdc = 0;
bool  sensorOk = false;

// ===================== Ausgang =====================
bool heaterOut = false;
int  stageOut = DEFAULT_STAGE;
int  pwmOut = -1;

// ===================== Zeitgeber ===================
unsigned long lastMqttAttempt = 0;
unsigned long lastMeasure = 0;
unsigned long lastDisplay = 0;
unsigned long lastStatus = 0;
unsigned long lastTempPublish = 0;
unsigned long wifiLostSince = 0;
unsigned long restartAt = 0;
bool statusDirty = true;
volatile bool ntpSynced = false;
unsigned long lastRtcSync = 0;

// ===================== Tasten ======================
enum ButtonAction { BTN_TEMP_UP, BTN_TEMP_DOWN, BTN_VORLAUF_UP, BTN_VORLAUF_DOWN, BTN_HEATER };

struct Button {
  uint8_t pin;
  ButtonAction action;
  bool stable;
  bool lastRaw;
  unsigned long changed;
};

Button buttons[] = {
  {PIN_TASTER3, BTN_TEMP_UP,      LOW, LOW, 0},
  {PIN_TASTER2, BTN_TEMP_DOWN,    LOW, LOW, 0},
  {PIN_TASTER5, BTN_VORLAUF_UP,   LOW, LOW, 0},
  {PIN_TASTER4, BTN_VORLAUF_DOWN, LOW, LOW, 0},
  {PIN_TASTER1, BTN_HEATER,       LOW, LOW, 0},
};
const size_t BUTTON_COUNT = sizeof(buttons) / sizeof(buttons[0]);

// ===================== Hilfsfunktionen =============
String topicFor(const char* sub) {
  return String(MQTT_BASE) + sub;
}

void publish(const char* sub, const String& value, bool retain = false) {
  if (mqtt.connected()) mqtt.publish(topicFor(sub).c_str(), value.c_str(), retain);
}

const char* modeName() {
  switch (mode) {
    case MODE_REMOTE:   return "remote";
    case MODE_FALLBACK: return "fallback";
    default:            return "startup";
  }
}

bool timeValid() {
  return time(nullptr) > 1700000000;
}

void markRemote() {
  lastRemote = millis();
  remoteSeen = true;
}

String formatSetpoint(float v) {
  // 21 statt 21.0, 21.5 bleibt 21.5
  if (fabsf(v - roundf(v)) < 0.01f) return String((int)roundf(v));
  return String(v, 1);
}

float clampSetpoint(float v) {
  v = roundf(v / SETPOINT_STEP) * SETPOINT_STEP;
  return constrain(v, SETPOINT_MIN, SETPOINT_MAX);
}

// ===================== Einstellungen speichern =====
void loadSettings() {
  EEPROM.begin(64);
  EEPROM.get(0, settings);
  bool valid = settings.magic == SETTINGS_MAGIC && !isnan(settings.setpoint) &&
               settings.setpoint >= SETPOINT_MIN && settings.setpoint <= SETPOINT_MAX &&
               settings.stage >= STAGE_MIN && settings.stage <= STAGE_MAX && settings.enabled <= 1;
  if (!valid) {
    settings = {SETTINGS_MAGIC, SETPOINT_DEFAULT, DEFAULT_STAGE, 1};
    Serial.println("Keine gespeicherten Einstellungen, verwende Standardwerte");
  }
  Serial.printf("Einstellungen: Soll %.1f, Stufe %d, %s\n", settings.setpoint, settings.stage,
                settings.enabled ? "an" : "aus");
}

void settingsLoop() {
  if (settingsDirty && millis() - settingsChanged > SETTINGS_SAVE_DELAY) {
    settingsDirty = false;
    EEPROM.put(0, settings);
    EEPROM.commit();
    Serial.println("Einstellungen gespeichert");
  }
}

void publishSetting(const char* which) {
  if (!strcmp(which, "setpoint")) publish("state/setpoint", formatSetpoint(settings.setpoint), true);
  if (!strcmp(which, "vorlauf"))  publish("state/vorlauf", String(settings.stage), true);
  if (!strcmp(which, "enabled"))  publish("state/enabled", settings.enabled ? "on" : "off", true);
}

void publishAllSettings() {
  publishSetting("setpoint");
  publishSetting("vorlauf");
  publishSetting("enabled");
}

// Ändert eine Einstellung. Meldet den Wert zurück, wenn er sich geändert hat
// oder begrenzt werden musste (damit das Dashboard den gültigen Wert zeigt).
void setSetpoint(float requested) {
  float v = clampSetpoint(requested);
  bool changed = fabsf(v - settings.setpoint) > 0.01f;
  if (changed) {
    settings.setpoint = v;
    settingsDirty = true;
    settingsChanged = millis();
    statusDirty = true;
  }
  if (changed || fabsf(v - requested) > 0.01f) publishSetting("setpoint");
}

void setStage(int requested) {
  int v = constrain(requested, STAGE_MIN, STAGE_MAX);
  bool changed = v != settings.stage;
  if (changed) {
    settings.stage = v;
    settingsDirty = true;
    settingsChanged = millis();
    statusDirty = true;
  }
  if (changed || v != requested) publishSetting("vorlauf");
}

void setEnabled(bool on) {
  if ((settings.enabled == 1) != on) {
    settings.enabled = on ? 1 : 0;
    settingsDirty = true;
    settingsChanged = millis();
    statusDirty = true;
    publishSetting("enabled");
  }
}

bool parseOnOff(const String& msg, bool& out) {
  if (msg == "on" || msg == "true" || msg == "1" || msg == "ein")  { out = true;  return true; }
  if (msg == "off" || msg == "false" || msg == "0" || msg == "aus") { out = false; return true; }
  return false;
}

// Im Automatikbetrieb sind Soll und Vorlauf gesperrt – außer im Notbetrieb,
// denn dann rechnet Node-RED nichts mehr.
bool manualLocked() {
  return autoMode && mode != MODE_FALLBACK;
}

// ===================== MQTT ========================
void onMqtt(char* topic, byte* payload, unsigned int length) {
  String t(topic);
  String msg;
  msg.reserve(length);
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  msg.trim();

  if (!t.startsWith(MQTT_BASE)) return;
  String sub = t.substring(strlen(MQTT_BASE));

  // heaterOn/Off und Vorlauftemp sind retained: der Broker liefert sie bei jeder Verbindung
  // erneut, auch wenn Node-RED nicht läuft. Als Lebenszeichen zählt deshalb nur Reboot = 1.
  if (sub == "heaterOn/Off") {
    bool on;
    if (parseOnOff(msg, on)) remoteHeaterOn = on;
    statusDirty = true;
  } else if (sub == "Vorlauftemp") {
    int s = msg.toInt();
    if (s >= STAGE_MIN && s <= STAGE_MAX) {
      remoteStage = s;
      statusDirty = true;
    }
  } else if (sub == "Reboot") {
    if (msg == "1") {
      markRemote();                           // Node-RED lebt
    } else if (msg == "0" && millis() > BOOT_GRACE) {
      restartAt = millis() + 500;             // Neustart außerhalb des Callbacks
    }
  } else if (sub == "cmd/setpoint") {
    if (msg.length() && !manualLocked()) setSetpoint(msg.toFloat());
  } else if (sub == "cmd/vorlauf") {
    if (msg.length() && !manualLocked()) setStage(msg.toInt());
  } else if (sub == "automode") {
    bool on;
    if (parseOnOff(msg, on) && on != autoMode) {
      autoMode = on;
      statusDirty = true;
      lastDisplay = 0;
      // Zurück im Handbetrieb: eigene Werte wieder ans Dashboard melden
      if (!autoMode) {
        publishSetting("setpoint");
        publishSetting("vorlauf");
      }
    }
  } else if (sub == "cmd/enabled") {
    bool on;
    if (parseOnOff(msg, on)) setEnabled(on);
  } else if (sub == "targetTemp") {
    targetTempString = msg;
  } else if (sub == "current-temperature/get") {
    currentTempString = msg;
  } else if (sub == "HeizungStatus") {
    statusString = msg;
  }
}

void mqttLoop() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connected()) {
    mqtt.loop();
    return;
  }
  if (millis() - lastMqttAttempt < MQTT_RETRY_INTERVAL) return;
  lastMqttAttempt = millis();

  String will = topicFor("online");
#ifdef MQTT_USE_AUTH
  bool ok = mqtt.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASSWORD, will.c_str(), 1, true, "0");
#else
  bool ok = mqtt.connect(MQTT_CLIENT_ID, will.c_str(), 1, true, "0");
#endif
  if (!ok) {
    Serial.printf("MQTT-Verbindung fehlgeschlagen, rc=%d\n", mqtt.state());
    return;
  }
  Serial.println("MQTT verbunden");
  publish("online", "1", true);
  // Zuerst den eigenen Stand melden, dann abonnieren
  publishAllSettings();
  const char* subs[] = {"heaterOn/Off", "Vorlauftemp", "Reboot", "cmd/setpoint", "cmd/vorlauf",
                        "cmd/enabled", "automode", "targetTemp", "current-temperature/get", "HeizungStatus"};
  for (const char* s : subs) mqtt.subscribe(topicFor(s).c_str(), 1);
  // Sofort melden, damit Node-RED mit Reboot = 1 antwortet und nicht erst nach STATUS_INTERVAL
  publish("Watchdog", "Alive");
  lastStatus = millis();
  statusDirty = true;
}

// ===================== WLAN / OTA ==================
void setupOTA() {
  ArduinoOTA.setHostname(WIFI_HOSTNAME);
#ifdef OTA_PASSWORD
  ArduinoOTA.setPassword(OTA_PASSWORD);
#endif
  ArduinoOTA.onStart([]() {
    analogWrite(PIN_HEATER, 0);  // während des Updates Therme aus
    if (displayOk) {
      display.clearDisplay();
      display.setTextSize(1);
      display.setCursor(0, 0);
      display.println("OTA Update ...");
      display.display();
    }
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    if (displayOk && total > 0) {
      display.fillRect(0, 20, 128, 10, SSD1306_BLACK);
      display.setCursor(0, 20);
      display.printf("%u%%", progress / (total / 100));
      display.display();
    }
  });
  ArduinoOTA.begin();
  otaStarted = true;
  Serial.println("OTA bereit");
}

void wifiLoop() {
  if (WiFi.status() == WL_CONNECTED) {
    wifiLostSince = 0;
    if (!otaStarted) setupOTA();
    return;
  }
  if (wifiLostSince == 0) wifiLostSince = millis();
  // Der ESP verbindet sich selbst neu; nur als letzte Maßnahme neu starten
  if (millis() - wifiLostSince > WIFI_REBOOT_TIMEOUT) {
    Serial.println("WLAN zu lange weg, Neustart");
    if (settingsDirty) { EEPROM.put(0, settings); EEPROM.commit(); }
    ESP.restart();
  }
}

// ===================== Zeit ========================
void setupTime() {
  // Bis NTP antwortet, die Zeit aus der DS3231 übernehmen (dort steht UTC)
  if (rtcOk && !rtc.lostPower()) {
    struct timeval tv = {(time_t)rtc.now().unixtime(), 0};
    settimeofday(&tv, nullptr);
  }
  settimeofday_cb([](bool fromSntp) {
    if (fromSntp) ntpSynced = true;
  });
  configTime(TZ_STRING, NTP_SERVER1, NTP_SERVER2);
}

void timeLoop() {
  // Nach NTP-Synchronisation, höchstens alle 6 h, die RTC nachstellen
  if (ntpSynced && rtcOk && (lastRtcSync == 0 || millis() - lastRtcSync > 6UL * 3600UL * 1000UL)) {
    ntpSynced = false;
    lastRtcSync = millis();
    rtc.adjust(DateTime((uint32_t)time(nullptr)));
    Serial.println("RTC aus NTP gestellt");
  }
}

// ===================== I2C =========================
void i2cBusReset() {
  pinMode(SDA_PIN, INPUT_PULLUP);
  pinMode(SCL_PIN, INPUT_PULLUP);
  delay(50);
  if (digitalRead(SDA_PIN) == LOW || digitalRead(SCL_PIN) == LOW) {
    Serial.println("I2C-Bus blockiert, setze zurück");
    pinMode(SCL_PIN, OUTPUT);
    for (int i = 0; i < 16; i++) {
      digitalWrite(SCL_PIN, HIGH);
      delayMicroseconds(5);
      digitalWrite(SCL_PIN, LOW);
      delayMicroseconds(5);
    }
    pinMode(SCL_PIN, INPUT_PULLUP);
  }
}

// ===================== Fühler ======================
void measureTemperature() {
  long sum = 0;
  const int samples = 8;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(A0);
    delay(1);
  }
  lastAdc = sum / samples;
  float t = ntcTemperature(lastAdc);

  sensorOk = !isnan(t) && t >= TEMP_VALID_MIN && t <= TEMP_VALID_MAX;
  if (!sensorOk) {
    roomTemp = NAN;
    return;
  }
  roomTemp = isnan(roomTemp) ? t : roomTemp * 0.8f + t * 0.2f;  // leichte Glättung
}

// ===================== Tasten ======================
void onButton(ButtonAction action) {
  if (manualLocked() && action != BTN_HEATER) {
    lockNoticeUntil = millis() + 2000;  // "AUTO - gesperrt" kurz anzeigen
    lastDisplay = 0;
    return;
  }
  switch (action) {
    case BTN_TEMP_UP:      setSetpoint(settings.setpoint + SETPOINT_STEP); break;
    case BTN_TEMP_DOWN:    setSetpoint(settings.setpoint - SETPOINT_STEP); break;
    case BTN_VORLAUF_UP:   setStage(settings.stage + 1); break;
    case BTN_VORLAUF_DOWN: setStage(settings.stage - 1); break;
    case BTN_HEATER:       setEnabled(!settings.enabled); break;
  }
  lastDisplay = 0;  // Anzeige sofort aktualisieren
}

void buttonsLoop() {
  unsigned long now = millis();
  for (size_t i = 0; i < BUTTON_COUNT; i++) {
    Button& b = buttons[i];
    bool raw = digitalRead(b.pin);
    if (raw != b.lastRaw) {
      b.lastRaw = raw;
      b.changed = now;
    }
    if (now - b.changed > DEBOUNCE_DELAY && raw != b.stable) {
      b.stable = raw;
      if (raw == HIGH) onButton(b.action);   // Taster schalten nach HIGH
    }
  }
}

// ===================== Regelung ====================
// Beim Wechsel in den Notbetrieb Soll und Stufe einmalig auf sinnvolle Startwerte anheben
// (im Automatikbetrieb kann der Soll z. B. auf 15 °C stehen). Danach gelten die Werte
// unverändert und lassen sich mit den Tastern im ganzen Bereich einstellen.
void enterFallback() {
  if (settings.setpoint < FALLBACK_SETPOINT_MIN) setSetpoint(FALLBACK_SETPOINT_MIN);
  if (settings.stage < FALLBACK_STAGE_MIN) setStage(FALLBACK_STAGE_MIN);
  fallbackHeat = false;
}

void controlLoop() {
  unsigned long now = millis();
  Mode newMode;
  if (remoteSeen && now - lastRemote < FALLBACK_TIMEOUT) newMode = MODE_REMOTE;
  else if (!remoteSeen && now < BOOT_GRACE)              newMode = MODE_STARTUP;
  else                                                   newMode = MODE_FALLBACK;

  if (newMode != mode) {
    if (newMode == MODE_FALLBACK) {
      Serial.println("Kein Lebenszeichen von Node-RED -> Notbetrieb");
      enterFallback();
    } else if (mode == MODE_FALLBACK) {
      Serial.println("Node-RED wieder da -> Fernsteuerung");
    }
    mode = newMode;
    statusDirty = true;
  }

  bool heat;
  int stage;
  switch (mode) {
    case MODE_REMOTE:
      heat = remoteHeaterOn;
      stage = remoteStage;
      break;
    case MODE_FALLBACK:
      // Soll und Vorlaufstufe kommen direkt aus den Einstellungen (Taster).
      // Bei "Heizung AUS" bleibt nur der Frostschutz.
      if (FALLBACK_USE_SENSOR && sensorOk) {
        float sp = settings.enabled ? settings.setpoint : FALLBACK_FROST_TEMP;
        if (roomTemp < sp - FALLBACK_HYSTERESIS) fallbackHeat = true;
        else if (roomTemp > sp + FALLBACK_HYSTERESIS) fallbackHeat = false;
        heat = fallbackHeat;
      } else {
        // ohne Fühler weiterheizen, die Heizkörper-Thermostate begrenzen;
        // bei "Heizung AUS" ohne Fühler bleibt die Therme aus
        heat = settings.enabled;
      }
      stage = settings.stage;
      break;
    default:  // MODE_STARTUP: auf Node-RED warten, Therme aus
      heat = false;
      stage = settings.stage;
      break;
  }

  // "Heizung AUS" gilt immer; im Notbetrieb bleibt der Frostschutz (siehe oben)
  if (!settings.enabled && mode != MODE_FALLBACK) heat = false;

  if (heat != heaterOut || stage != stageOut) statusDirty = true;
  heaterOut = heat;
  stageOut = stage;

  int pwm = heaterOut ? VorlaufTemp(stageOut) : 0;
  if (pwm != pwmOut) {
    analogWrite(PIN_HEATER, pwm);
    pwmOut = pwm;
  }
}

// ===================== Status ======================
void statusLoop() {
  unsigned long now = millis();
  bool due = now - lastStatus >= STATUS_INTERVAL;
  if (!due && !statusDirty) return;
  if (!mqtt.connected()) return;

  if (due) {
    lastStatus = now;
    publish("Watchdog", "Alive");
  }
  statusDirty = false;

  String json = "{";
  json += "\"mode\":\"" + String(modeName()) + "\"";
  json += ",\"automode\":" + String(autoMode ? "true" : "false");
  json += ",\"enabled\":" + String(settings.enabled ? "true" : "false");
  json += ",\"heater\":" + String(heaterOut ? "true" : "false");
  json += ",\"stage\":" + String(stageOut);
  json += ",\"flow_temp\":" + String(VorlaufCelsius(stageOut));
  json += ",\"setpoint\":" + formatSetpoint(settings.setpoint);
  json += ",\"manual_stage\":" + String(settings.stage);
  json += ",\"sensor_ok\":" + String(sensorOk ? "true" : "false");
  json += ",\"room_temp\":" + (sensorOk ? String(roomTemp, 1) : String("null"));
  json += ",\"adc\":" + String(lastAdc);
  json += ",\"rssi\":" + String(WiFi.RSSI());
  json += ",\"uptime\":" + String(now / 1000);
  json += "}";
  publish("status", json, true);
}

void temperaturePublishLoop() {
  if (millis() - lastTempPublish < STATUS_INTERVAL) return;
  lastTempPublish = millis();
  if (sensorOk) publish("fallback/temperature", String(roomTemp, 1));
}

// ===================== Display =====================
void displayLoop() {
  if (!displayOk) return;
  unsigned long now = millis();
  if (lastDisplay != 0 && now - lastDisplay < DISPLAY_UPDATE_INTERVAL) return;
  lastDisplay = now == 0 ? 1 : now;

  String timeStr = "--:--:--", dateStr = "--.--.----";
  if (timeValid()) {
    time_t t = time(nullptr);
    struct tm lt;
    localtime_r(&t, &lt);
    timeStr = twoDigits(lt.tm_hour) + ":" + twoDigits(lt.tm_min) + ":" + twoDigits(lt.tm_sec);
    dateStr = twoDigits(lt.tm_mday) + "." + twoDigits(lt.tm_mon + 1) + "." + String(lt.tm_year + 1900);
  }

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(timeStr);
  display.setCursor(65, 0);
  display.print(dateStr);

  display.setTextSize(2);
  display.setCursor(0, 15);
  if (mode == MODE_FALLBACK) {
    display.print("NOT ");
    display.print(sensorOk ? String(roomTemp, 1) : String("--"));
  } else {
    display.print("Room:");
    display.setCursor(75, 15);
    display.print(currentTempString);
  }

  display.setTextSize(1);
  display.setCursor(0, 45);
  if (!settings.enabled) display.print(heaterOut ? "Frostschutz" : "Heizung: AUS");
  // Freigegeben: "heizt", wenn die Therme läuft, sonst "bereit" (Raum ist warm genug)
  else display.print(heaterOut ? "AN - heizt" : "AN - bereit");
  display.setCursor(80, 45);
  display.print("Set:");
  // Im Automatikbetrieb das von Node-RED berechnete Ziel zeigen
  display.print(manualLocked() ? targetTempString : formatSetpoint(settings.setpoint));

  display.setCursor(0, 55);
  display.print("Vorlauf:");
  display.print(stageOut);
  display.print(" ");
  display.print(VorlaufCelsius(stageOut));
  display.print("C");
  // Rechts unten: A = Automatik, W = WLAN, M = MQTT
  display.setCursor(104, 55);
  display.print(manualLocked() ? "A" : " ");
  display.print(WiFi.status() == WL_CONNECTED ? "W" : "-");
  display.print(mqtt.connected() ? "M" : "-");

  if ((long)(lockNoticeUntil - millis()) > 0) {
    display.fillRect(0, 14, 128, 28, SSD1306_BLACK);
    display.setTextSize(2);
    display.setCursor(0, 15);
    display.print("AUTO -");
    display.setTextSize(1);
    display.setCursor(0, 33);
    display.print("Taster gesperrt");
  }

  display.display();
}

// ===================== Setup =======================
void setup() {
  // Zuerst den Ausgang sicher auf "aus"
  pinMode(PIN_HEATER, OUTPUT);
  analogWriteRange(255);
  analogWrite(PIN_HEATER, 0);
  pwmOut = 0;

  Serial.begin(115200);
  delay(200);
  Serial.println("\nVaillant-ESP startet");

  loadSettings();
  stageOut = settings.stage;

  for (size_t i = 0; i < BUTTON_COUNT; i++) pinMode(buttons[i].pin, INPUT);

  i2cBusReset();
  Wire.begin(SDA_PIN, SCL_PIN);

  displayOk = display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS);
  if (displayOk) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println("Start ...");
    display.display();
  } else {
    Serial.println("Display nicht gefunden, weiter ohne");
  }

  rtcOk = rtc.begin();
  if (!rtcOk) Serial.println("RTC nicht gefunden, weiter ohne");

  setupTime();

  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.hostname(WIFI_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  espClient.setTimeout(2000);
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  mqtt.setCallback(onMqtt);
  mqtt.setBufferSize(512);
  mqtt.setSocketTimeout(5);

  measureTemperature();
}

// ===================== Loop ========================
void loop() {
  wifiLoop();
  if (otaStarted) ArduinoOTA.handle();
  mqttLoop();
  timeLoop();

  if (millis() - lastMeasure >= TEMP_MEASURE_INTERVAL) {
    lastMeasure = millis();
    measureTemperature();
  }

  buttonsLoop();
  controlLoop();
  settingsLoop();
  statusLoop();
  temperaturePublishLoop();
  displayLoop();

  if (restartAt && (long)(millis() - restartAt) >= 0) {
    Serial.println("Neustart auf Anforderung von Node-RED");
    analogWrite(PIN_HEATER, 0);
    if (settingsDirty) { EEPROM.put(0, settings); EEPROM.commit(); }
    ESP.restart();
  }
}
