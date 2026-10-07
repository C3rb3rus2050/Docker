"""Treiber für Eurotronic / Euronics "Comet Blue" Heizkörperthermostate (Bluetooth LE)."""

import datetime as dt
import struct

TYPE = "cometblue"
DESCRIPTION = "Comet Blue Heizkörperthermostat"

# GATT-Characteristics
UUID_DATETIME = "47e9ee01-47e9-11e4-8939-164230d1df67"
UUID_FLAGS = "47e9ee2a-47e9-11e4-8939-164230d1df67"
UUID_TEMPS = "47e9ee2b-47e9-11e4-8939-164230d1df67"
UUID_BATTERY = "47e9ee2c-47e9-11e4-8939-164230d1df67"
UUID_PIN = "47e9ee30-47e9-11e4-8939-164230d1df67"

NO_CHANGE = -128  # "nicht ändern" im Temperatur-Block

# Was das Gerät anbietet (für Web-Oberfläche und bridge/devices).
# access: "r" = nur lesen, "rw" = lesen und setzen
EXPOSES = [
    {"name": "local_temperature", "label": "Raumtemperatur", "unit": "°C", "access": "r"},
    {"name": "current_heating_setpoint", "label": "Solltemperatur", "unit": "°C", "access": "rw",
     "min": 7.5, "max": 28.5, "step": 0.5},
    {"name": "comfort_temperature", "label": "Komforttemperatur", "unit": "°C", "access": "rw",
     "min": 7.5, "max": 28.5, "step": 0.5},
    {"name": "eco_temperature", "label": "Absenktemperatur", "unit": "°C", "access": "rw",
     "min": 7.5, "max": 28.5, "step": 0.5},
    {"name": "local_temperature_calibration", "label": "Offset", "unit": "°C", "access": "rw",
     "min": -5.0, "max": 5.0, "step": 0.5},
    {"name": "window_open_detection", "label": "Fenster-auf-Erkennung (Rohwert)", "unit": "", "access": "rw",
     "min": 0, "max": 127, "step": 1},
    {"name": "window_open_minutes", "label": "Fenster-auf-Dauer", "unit": "min", "access": "rw",
     "min": 0, "max": 127, "step": 1},
    {"name": "battery", "label": "Batterie", "unit": "%", "access": "r"},
]
_WRITABLE = {e["name"]: e for e in EXPOSES if e["access"] == "rw"}
_TEMP_KEYS = {"current_heating_setpoint", "comfort_temperature", "eco_temperature", "local_temperature_calibration"}


def matches(name: str | None) -> bool:
    """Erkennt das Gerät beim Scan am Bluetooth-Namen."""
    return bool(name) and "comet" in name.lower()


def parse_set(data) -> dict:
    """Zahl = Solltemperatur, sonst Objekt mit setzbaren Feldern. Prüft Bereiche."""
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        data = {"current_heating_setpoint": data}
    if not isinstance(data, dict) or not data:
        raise ValueError("Erwarte eine Zahl oder ein JSON-Objekt")
    unknown = set(data) - set(_WRITABLE)
    if unknown:
        raise ValueError(f"Nicht setzbar: {', '.join(sorted(unknown))}")
    changes = {}
    for key, value in data.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} muss eine Zahl sein")
        spec = _WRITABLE[key]
        if not spec["min"] <= value <= spec["max"]:
            raise ValueError(f"{key}={value} außerhalb {spec['min']}..{spec['max']}")
        changes[key] = value
    return changes


def _decode_temps(data: bytes) -> dict:
    cur, man, low, high, off, wod, wom = struct.unpack("<bbbbbbb", bytes(data[:7]))
    return {
        "local_temperature": cur / 2.0,
        "current_heating_setpoint": man / 2.0,
        "eco_temperature": low / 2.0,
        "comfort_temperature": high / 2.0,
        "local_temperature_calibration": off / 2.0,
        "window_open_detection": wod,
        "window_open_minutes": wom,
    }


def _encode_temps(changes: dict) -> bytes:
    def val(key):
        v = changes.get(key)
        if v is None:
            return NO_CHANGE
        return int(round(float(v) * 2)) if key in _TEMP_KEYS else int(v)

    return struct.pack(
        "<bbbbbbb",
        NO_CHANGE,  # Ist-Temperatur ist nur lesbar
        val("current_heating_setpoint"),
        val("eco_temperature"),
        val("comfort_temperature"),
        val("local_temperature_calibration"),
        val("window_open_detection"),
        val("window_open_minutes"),
    )


def _encode_datetime(t: dt.datetime) -> bytes:
    return struct.pack("<BBBBB", t.minute, t.hour, t.day, t.month, t.year - 2000)


async def session(address: str, options: dict, adapter: str | None,
                  changes: dict | None = None, sync_time: bool = False) -> dict:
    """Eine Verbindung: PIN senden, optional Uhrzeit/Werte schreiben, alles lesen."""
    from bleak import BleakClient

    kwargs = {"adapter": adapter} if adapter else {}
    async with BleakClient(address, timeout=20.0, **kwargs) as client:
        pin = int(options.get("pin", 0))
        await client.write_gatt_char(UUID_PIN, struct.pack("<I", pin), response=True)
        if sync_time:
            await client.write_gatt_char(UUID_DATETIME, _encode_datetime(dt.datetime.now()), response=True)
        if changes:
            await client.write_gatt_char(UUID_TEMPS, _encode_temps(changes), response=True)
        temps = _decode_temps(await client.read_gatt_char(UUID_TEMPS))
        battery = (await client.read_gatt_char(UUID_BATTERY))[0]
        flags = bytes(await client.read_gatt_char(UUID_FLAGS)).hex()

    state = dict(temps)
    state["battery"] = None if battery == 255 else battery
    state["flags"] = flags
    return state
