#ifndef FUNCTIONS_H
#define FUNCTIONS_H

#include <Arduino.h>

// PWM-Wert (0–255) für die Vorlaufstufe 1–9 (gemessene Werte der Therme)
int VorlaufTemp(int stage);

// Ungefähre Vorlauftemperatur der Stufe in °C (nur zur Anzeige)
int VorlaufCelsius(int stage);

// Temperatur aus dem ADC-Wert des Thermistors, NAN bei offenem/kurzgeschlossenem Fühler
float ntcTemperature(int adc);

// Zahl zweistellig mit führender Null
String twoDigits(int val);

#endif // FUNCTIONS_H
