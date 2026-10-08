#ifndef CONFIG_H
#define CONFIG_H

// ===================== Display =====================
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64
#define OLED_RESET    -1
#define OLED_ADDRESS  0x3C
#define DISPLAY_UPDATE_INTERVAL 1000UL   // ms

// ===================== Pins ========================
#define PIN_HEATER   2    // PWM-Ausgang zur Therme (GPIO2 muss beim Booten HIGH sein)
#define PIN_TASTER1  15   // Heizung Ein/Aus
#define PIN_TASTER2  12   // Temperatur runter
#define PIN_TASTER3  16   // Temperatur hoch
#define PIN_TASTER4  13   // Vorlauf runter
#define PIN_TASTER5  14   // Vorlauf hoch
#define SDA_PIN      4    // I2C für RTC und Display
#define SCL_PIN      5
#define DEBOUNCE_DELAY 50UL // ms

// ===================== MQTT ========================
#define MQTT_BASE      "home/vaillant/esp1/"
#define MQTT_CLIENT_ID "ESP1_Vaillant"
#define MQTT_RETRY_INTERVAL 5000UL       // ms zwischen Verbindungsversuchen

// ===================== Zeit ========================
// Mitteleuropa mit automatischer Sommer-/Winterzeit. Die DS3231 speichert UTC.
#define TZ_STRING   "CET-1CEST,M3.5.0,M10.5.0/3"
#define NTP_SERVER1 "pool.ntp.org"
#define NTP_SERVER2 "time.nist.gov"

// ===================== Thermistor an A0 ============
// Schaltung: 3,3 V -- Festwiderstand -- A0 -- NTC -- GND   (NTC_TO_GND = true)
//        oder 3,3 V -- NTC -- A0 -- Festwiderstand -- GND   (NTC_TO_GND = false)
#define NTC_R25         100000.0f  // NTC-Widerstand bei 25 °C
#define NTC_BETA        3950.0f    // B-Wert laut Datenblatt (häufig 3950)
#define NTC_SERIES_R    100000.0f  // Festwiderstand im Spannungsteiler
#define NTC_TO_GND      true
#define SUPPLY_V        3.3f       // Versorgung des Spannungsteilers
#define ADC_FULLSCALE_V 3.2f       // NodeMCU hat einen Spannungsteiler an A0: 0–3,2 V
#define TEMP_OFFSET     0.0f       // Korrektur in °C nach Vergleich mit einem Thermometer
#define TEMP_MEASURE_INTERVAL 3000UL
#define TEMP_VALID_MIN  0.0f       // außerhalb dieses Bereichs gilt der Fühler als gestört
#define TEMP_VALID_MAX  40.0f

// ===================== Einstellungen (Taster/Node-RED) =====
// Soll, Vorlaufstufe und Ein/Aus verwaltet der ESP. Taster und Node-RED-Dashboard
// ändern dieselben Werte; sie werden im Flash gespeichert und über MQTT gemeldet.
#define SETPOINT_DEFAULT    20.0f
#define SETPOINT_MIN        10.0f
#define SETPOINT_MAX        28.0f
#define SETPOINT_STEP       0.5f
#define STAGE_MIN           1
#define STAGE_MAX           9
#define SETTINGS_SAVE_DELAY 10000UL   // ms nach der letzten Änderung in den Flash schreiben

// ===================== Start und Notbetrieb ========
#define DEFAULT_STAGE       4                    // Vorlaufstufe ohne gespeicherte Einstellung (~40 °C)
#define BOOT_GRACE          (3UL * 60UL * 1000UL)  // so lange nach dem Start auf Node-RED warten
#define FALLBACK_TIMEOUT    (15UL * 60UL * 1000UL) // ohne Lebenszeichen -> Notbetrieb
#define FALLBACK_USE_SENSOR true                 // false: Notbetrieb ohne Fühler, durchgehend heizen
// Beim Wechsel in den Notbetrieb werden Soll und Stufe einmalig mindestens hierauf gesetzt,
// danach sind sie mit den Tastern frei einstellbar.
#define FALLBACK_SETPOINT_MIN 18.0f
#define FALLBACK_HYSTERESIS 0.5f
#define FALLBACK_STAGE_MIN  4                    // ~40 °C
#define WIFI_REBOOT_TIMEOUT (30UL * 60UL * 1000UL) // ohne WLAN so lange warten, dann Neustart
#define STATUS_INTERVAL     60000UL              // Status und "Alive" an MQTT

#endif // CONFIG_H
