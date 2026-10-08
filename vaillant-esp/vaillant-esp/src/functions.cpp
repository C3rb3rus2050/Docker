#include "functions.h"
#include "config.h"
#include <math.h>

// Gemessene Werte im 10-Bit-Bereich (0–1023), Ausgabe im 8-Bit-Bereich (analogWriteRange 255)
static const int VORLAUF_ADC[9] = {
    739,   // 1: ~10 °C
    775,   // 2: ~20 °C
    810,   // 3: ~30 °C
    846,   // 4: ~40 °C
    881,   // 5: ~50 °C
    917,   // 6: ~60 °C
    952,   // 7: ~70 °C
    988,   // 8: ~75 °C
    1023,  // 9: ~82 °C
};
static const int VORLAUF_C[9] = {10, 20, 30, 40, 50, 60, 70, 75, 82};

int VorlaufTemp(int stage) {
    if (stage < 1 || stage > 9) stage = 1;
    return VORLAUF_ADC[stage - 1] / 4;
}

int VorlaufCelsius(int stage) {
    if (stage < 1 || stage > 9) return 0;
    return VORLAUF_C[stage - 1];
}

float ntcTemperature(int adc) {
    if (adc <= 2 || adc >= 1021) return NAN;  // Fühler offen oder Kurzschluss

    float v = (adc / 1023.0f) * ADC_FULLSCALE_V;
    if (v <= 0.0f || v >= SUPPLY_V) return NAN;

    float r = NTC_TO_GND ? NTC_SERIES_R * v / (SUPPLY_V - v)
                         : NTC_SERIES_R * (SUPPLY_V - v) / v;
    if (r <= 0.0f) return NAN;

    // Beta-Gleichung
    float invT = 1.0f / 298.15f + logf(r / NTC_R25) / NTC_BETA;
    return (1.0f / invT) - 273.15f + TEMP_OFFSET;
}

String twoDigits(int val) {
    if (val < 10) return "0" + String(val);
    return String(val);
}
