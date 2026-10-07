"""Simulierte Comet-Blue-Thermostate zum Testen ohne Bluetooth (Start mit --mock)."""

import asyncio
import random

import driver_cometblue

FAKE_DEVICES = {
    "E0:E5:CF:00:00:01": {"name": "Comet Blue", "rssi": -58, "pin": 0},
    "E0:E5:CF:00:00:02": {"name": "Comet Blue", "rssi": -71, "pin": 0},
    "E0:E5:CF:00:00:03": {"name": "Comet Blue", "rssi": -84, "pin": 123456},
    "11:22:33:44:55:66": {"name": "Mi Band", "rssi": -60, "pin": 0},
}

_values: dict[str, dict] = {}


def _initial():
    return {
        "local_temperature": round(random.uniform(18, 22) * 2) / 2,
        "current_heating_setpoint": 20.0,
        "eco_temperature": 17.0,
        "comfort_temperature": 21.0,
        "local_temperature_calibration": 0.0,
        "window_open_detection": 4,
        "window_open_minutes": 10,
        "battery": random.randint(40, 100),
        "flags": "000000",
    }


async def fake_session(address, options, adapter, changes=None, sync_time=False):
    await asyncio.sleep(1.0)
    fake = FAKE_DEVICES.get(address)
    if fake is None:
        raise TimeoutError("Gerät nicht erreichbar")
    if int(options.get("pin", 0)) != fake["pin"]:
        raise PermissionError("Falsche PIN")
    values = _values.setdefault(address, _initial())
    if changes:
        values.update(changes)
    return dict(values)


async def fake_discover(seconds):
    await asyncio.sleep(min(seconds, 2))
    return [(addr, d["name"], d["rssi"]) for addr, d in FAKE_DEVICES.items()]


def install(core):
    driver_cometblue.session = fake_session
    core.discover = fake_discover
