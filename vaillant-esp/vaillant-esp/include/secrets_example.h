#ifndef SECRET_H
#define SECRET_H

// Kopieren nach secrets.h und anpassen

// WLAN
#define WIFI_SSID      "YourWiFiSSID"
#define WIFI_PASSWORD  "YourWiFiPassword"
#define WIFI_HOSTNAME  "Vaillant"

// MQTT-Broker
#define MQTT_SERVER    "192.168.178.51"
#define MQTT_PORT      1883

// Nur einkommentieren, wenn der Broker eine Anmeldung verlangt:
// #define MQTT_USE_AUTH
#define MQTT_USER      "mqtt_username"
#define MQTT_PASSWORD  "mqtt_password"

// OTA-Passwort (optional, empfohlen)
#define OTA_PASSWORD   "SuperSafePassword"

#endif // SECRET_H
