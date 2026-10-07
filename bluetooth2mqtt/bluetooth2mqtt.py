#!/usr/bin/env python3
"""
bluetooth2mqtt – Bluetooth-LE-Geräte über MQTT steuern, nach dem Vorbild von zigbee2mqtt.

MQTT-API (base_topic = "bluetooth2mqtt"):
  bluetooth2mqtt/<name>                     Zustand als JSON (retained)
  bluetooth2mqtt/<name>/availability        {"state":"online"|"offline"} (retained)
  bluetooth2mqtt/<name>/set                 Zahl (= Solltemperatur) oder JSON-Objekt
  bluetooth2mqtt/<name>/set/<feld>          einzelnen Wert setzen
  bluetooth2mqtt/<name>/get                 sofort neu auslesen
  bluetooth2mqtt/bridge/state               {"state":"online"|"offline"} (retained, Last Will)
  bluetooth2mqtt/bridge/info                Version und Einstellungen (retained)
  bluetooth2mqtt/bridge/devices             Liste aller angelernten Geräte (retained)
  bluetooth2mqtt/bridge/event               device_added, device_removed, device_renamed, scan_…
  bluetooth2mqtt/bridge/logging             Fehlermeldungen
  bluetooth2mqtt/bridge/request/<befehl>    Anfragen, Antwort auf bridge/response/<befehl>:
      scan            {"time": 15}
      device/add      {"address": "AA:BB:..", "friendly_name": "wohnzimmer", "pin": 0}
      device/remove   {"id": "wohnzimmer"}
      device/rename   {"from": "alt", "to": "neu"}
      device/options  {"id": "wohnzimmer", "options": {"pin": 123456}}

Start:  python bluetooth2mqtt.py --data ./data
"""

import argparse
import asyncio
import collections
import copy
import datetime as dt
import json
import logging
import os
import re
from pathlib import Path

import driver_cometblue
from errors import DeviceError, NotFound

VERSION = "1.0.0"
DRIVERS = {driver_cometblue.TYPE: driver_cometblue}

DEFAULT_CONFIG = {
    "mqtt": {
        "server": "localhost",
        "port": 1883,
        "user": "",
        "password": "",
        "base_topic": "bluetooth2mqtt",
        "client_id": "bluetooth2mqtt",
    },
    "frontend": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8099,
        "auth_token": "",
    },
    "bluetooth": {
        "adapter": "hci0",
        "poll_interval": 600,
        "sync_time_daily": True,
    },
}

BLE_TIMEOUT = 60          # Sekunden für eine komplette Verbindung
RETRIES_POLL = 3          # Versuche beim regelmäßigen Auslesen
RETRIES_INTERACTIVE = 2   # Versuche bei Befehlen aus Web/MQTT
RETRY_DELAY = 8

MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
NAME_RE = re.compile(r"^[\w\-.]{1,40}$")

log = logging.getLogger("bluetooth2mqtt")


class LogBuffer(logging.Handler):
    """Hält die letzten Logzeilen für die Web-Oberfläche."""

    def __init__(self, size=300):
        super().__init__()
        self.lines = collections.deque(maxlen=size)

    def emit(self, record):
        self.lines.append({
            "time": dt.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        })


LOG_BUFFER = LogBuffer()


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_json(path: Path, default):
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class Job:
    __slots__ = ("address", "device", "changes", "future", "retries")

    def __init__(self, address, device=None, changes=None, future=None, retries=RETRIES_POLL):
        self.address = address
        self.device = device
        self.changes = changes
        self.future = future
        self.retries = retries


class Core:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        cfg_path = data_dir / "configuration.json"
        if not cfg_path.exists():
            save_json(cfg_path, DEFAULT_CONFIG)
            log.info("Neue Konfiguration angelegt: %s", cfg_path)
        self.config = deep_merge(DEFAULT_CONFIG, load_json(cfg_path, {}))

        self.devices_path = data_dir / "devices.json"
        # Adresse -> {"friendly_name", "type", "options": {"pin": 0}}
        self.devices: dict[str, dict] = load_json(self.devices_path, {})

        self.base = self.config["mqtt"]["base_topic"].rstrip("/")
        bt = self.config["bluetooth"]
        self.adapter = bt.get("adapter") or None
        self.poll_interval = max(60, int(bt.get("poll_interval", 600)))
        self.sync_daily = bool(bt.get("sync_time_daily", True))

        self.state: dict[str, dict] = {}
        self.available: dict[str, bool] = {}
        self.last_sync: dict[str, dt.date] = {}
        self.pending_reads: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.ble_lock = asyncio.Lock()

        self.scan_results: list[dict] = []
        self.scan_running = False
        self.last_scan: str | None = None

        self.mqtt = None
        self.started = now_iso()

    # ------------------------------------------------------------ Hilfen

    def topic(self, *parts) -> str:
        return "/".join([self.base, *parts])

    def resolve(self, ident) -> str:
        """Friendly name oder Adresse -> Adresse."""
        ident = str(ident).strip()
        if ident.upper() in self.devices:
            return ident.upper()
        for address, dev in self.devices.items():
            if dev["friendly_name"].lower() == ident.lower():
                return address
        raise NotFound(f"Gerät '{ident}' ist nicht angelernt")

    def check_name(self, name, exclude: str | None = None) -> str:
        name = str(name).strip()
        if not NAME_RE.match(name):
            raise ValueError("Name: 1–40 Zeichen, nur Buchstaben, Ziffern, _ - . (keine Leerzeichen)")
        if name.lower() == "bridge":
            raise ValueError("'bridge' ist reserviert")
        for address, dev in self.devices.items():
            if address != exclude and dev["friendly_name"].lower() == name.lower():
                raise ValueError(f"Name '{name}' ist schon vergeben")
        return name

    @staticmethod
    def check_pin(pin) -> int:
        try:
            pin = int(str(pin).strip() or 0)
        except ValueError:
            raise ValueError("PIN muss eine Zahl sein")
        if not 0 <= pin <= 999999:
            raise ValueError("PIN muss zwischen 0 und 999999 liegen")
        return pin

    def device_info(self, address: str, full: bool = False) -> dict:
        dev = self.devices[address]
        drv = DRIVERS[dev["type"]]
        info = {
            "address": address,
            "friendly_name": dev["friendly_name"],
            "type": dev["type"],
            "description": drv.DESCRIPTION,
            "exposes": drv.EXPOSES,
        }
        if full:
            info["state"] = self.state.get(address)
            info["available"] = self.available.get(address)
            info["pin_set"] = bool(dev.get("options", {}).get("pin"))
        return info

    def save_devices(self):
        save_json(self.devices_path, self.devices)

    def logs(self):
        return list(LOG_BUFFER.lines)

    def info(self) -> dict:
        return {
            "version": VERSION,
            "started": self.started,
            "mqtt_connected": self.mqtt is not None,
            "base_topic": self.base,
            "poll_interval": self.poll_interval,
            "adapter": self.adapter,
            "scan_running": self.scan_running,
            "last_scan": self.last_scan,
            "queue": self.queue.qsize(),
        }

    # ------------------------------------------------------------ MQTT-Ausgabe

    async def publish(self, topic, payload, retain=False):
        client = self.mqtt
        if client is None:
            return
        if not isinstance(payload, (str, bytes)):
            payload = json.dumps(payload, ensure_ascii=False)
        try:
            await client.publish(topic, payload, qos=1, retain=retain)
        except Exception as e:
            log.debug("Publish auf %s fehlgeschlagen: %s", topic, e)

    async def publish_devices(self):
        await self.publish(self.topic("bridge", "devices"),
                           [self.device_info(a) for a in self.devices], retain=True)

    async def publish_device_state(self, address):
        name = self.devices[address]["friendly_name"]
        if address in self.state:
            await self.publish(self.topic(name), self.state[address], retain=True)
        if address in self.available:
            await self.publish(self.topic(name, "availability"),
                               {"state": "online" if self.available[address] else "offline"}, retain=True)

    async def clear_device_topics(self, name):
        await self.publish(self.topic(name), "", retain=True)
        await self.publish(self.topic(name, "availability"), "", retain=True)

    async def event(self, kind, data):
        await self.publish(self.topic("bridge", "event"), {"type": kind, "data": data})

    async def on_mqtt_connected(self):
        await self.publish(self.topic("bridge", "state"), {"state": "online"}, retain=True)
        await self.publish(self.topic("bridge", "info"), {
            "version": VERSION,
            "config": {"base_topic": self.base, "poll_interval": self.poll_interval, "adapter": self.adapter},
            "frontend": {"enabled": self.config["frontend"]["enabled"], "port": self.config["frontend"]["port"]},
        }, retain=True)
        await self.publish_devices()
        for address in self.devices:
            await self.publish_device_state(address)

    # ------------------------------------------------------------ Bluetooth

    async def discover(self, seconds: int):
        """Liefert [(adresse, name, rssi)] aller Geräte in Reichweite."""
        from bleak import BleakScanner

        kwargs = {"adapter": self.adapter} if self.adapter else {}
        found = await BleakScanner.discover(timeout=seconds, return_adv=True, **kwargs)
        return [(addr, dev.name or adv.local_name or "", adv.rssi) for addr, (dev, adv) in found.items()]

    def request_read(self, address):
        if address not in self.pending_reads:
            self.pending_reads.add(address)
            self.queue.put_nowait(Job(address))

    async def run_job(self, address, changes=None, device=None) -> dict:
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait(Job(address, device, changes, future, RETRIES_INTERACTIVE))
        return await future

    async def worker(self):
        """Arbeitet alle Bluetooth-Zugriffe nacheinander ab (nur eine Verbindung gleichzeitig)."""
        while True:
            job = await self.queue.get()
            address = job.address
            if job.future is None and job.changes is None:
                self.pending_reads.discard(address)
            device = job.device or self.devices.get(address)
            if device is None:  # inzwischen entfernt
                continue
            driver = DRIVERS[device["type"]]
            today = dt.date.today()
            sync = self.sync_daily and self.last_sync.get(address) != today

            state, error = None, None
            async with self.ble_lock:
                for attempt in range(1, job.retries + 1):
                    try:
                        state = await asyncio.wait_for(
                            driver.session(address, device.get("options", {}), self.adapter, job.changes, sync),
                            BLE_TIMEOUT)
                        break
                    except Exception as e:  # BlueZ/D-Bus werfen sehr unterschiedliche Fehler
                        error = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                        log.warning("%s: Versuch %d/%d fehlgeschlagen: %s",
                                    device["friendly_name"], attempt, job.retries, error)
                        if attempt < job.retries:
                            await asyncio.sleep(RETRY_DELAY)
                await asyncio.sleep(1.5)  # dem Bluetooth-Stack kurz Luft lassen

            known = address in self.devices
            if state is None:
                if known:
                    self.available[address] = False
                    await self.publish_device_state(address)
                if job.future and not job.future.done():
                    job.future.set_exception(DeviceError(f"Keine Verbindung zu {device['friendly_name']}: {error}"))
                continue

            if sync:
                self.last_sync[address] = today
            state["last_seen"] = now_iso()
            if known:
                self.state[address] = state
                self.available[address] = True
                log.info("%s: %.1f °C, Soll %.1f °C, Batterie %s %%", device["friendly_name"],
                         state.get("local_temperature", 0), state.get("current_heating_setpoint", 0),
                         state.get("battery"))
                await self.publish_device_state(address)
            if job.future and not job.future.done():
                job.future.set_result(state)

    async def poller(self):
        await asyncio.sleep(3)
        while True:
            for address in list(self.devices):
                self.request_read(address)
            await asyncio.sleep(self.poll_interval)

    # ------------------------------------------------------------ Geräteverwaltung

    async def scan(self, seconds=15) -> list:
        seconds = max(5, min(60, int(seconds)))
        if self.scan_running:
            raise ValueError("Es läuft bereits eine Suche")
        self.scan_running = True
        log.info("Suche %d s nach Bluetooth-Geräten ...", seconds)
        await self.event("scan_started", {"time": seconds})
        try:
            async with self.ble_lock:
                found = await self.discover(seconds)
        except Exception as e:
            raise DeviceError(f"Bluetooth-Suche fehlgeschlagen: {e}")
        finally:
            self.scan_running = False

        results = []
        for address, name, rssi in found:
            address = address.upper()
            for typ, drv in DRIVERS.items():
                if drv.matches(name):
                    dev = self.devices.get(address)
                    results.append({
                        "address": address, "name": name, "rssi": rssi,
                        "type": typ, "description": drv.DESCRIPTION,
                        "added": dev is not None,
                        "friendly_name": dev["friendly_name"] if dev else None,
                    })
                    break
        results.sort(key=lambda r: -(r["rssi"] or -999))
        self.scan_results = results
        self.last_scan = now_iso()
        log.info("Suche beendet: %d passende Geräte gefunden", len(results))
        await self.event("scan_finished", {"devices": results})
        return results

    def _refresh_scan_flags(self):
        for r in self.scan_results:
            dev = self.devices.get(r["address"])
            r["added"] = dev is not None
            r["friendly_name"] = dev["friendly_name"] if dev else None

    async def add_device(self, address, friendly_name, pin=0, typ=None) -> dict:
        address = str(address).strip().upper()
        if not MAC_RE.match(address):
            raise ValueError("Ungültige Bluetooth-Adresse, erwartet z. B. AA:BB:CC:DD:EE:FF")
        if address in self.devices:
            raise ValueError(f"{address} ist bereits als '{self.devices[address]['friendly_name']}' angelernt")
        name = self.check_name(friendly_name)
        if typ is None:
            typ = next((r["type"] for r in self.scan_results if r["address"] == address), None)
            if typ is None and len(DRIVERS) == 1:
                typ = next(iter(DRIVERS))
        if typ not in DRIVERS:
            raise ValueError(f"Unbekannter Gerätetyp: {typ}")
        device = {"friendly_name": name, "type": typ, "options": {"pin": self.check_pin(pin)}}

        log.info("Lerne %s als '%s' an, prüfe Verbindung und PIN ...", address, name)
        state = await self.run_job(address, device=device)

        if address in self.devices:
            raise ValueError(f"{address} wurde inzwischen schon angelernt")
        self.check_name(name)  # könnte inzwischen vergeben sein
        self.devices[address] = device
        self.save_devices()
        self.state[address] = state
        self.available[address] = True
        self._refresh_scan_flags()
        log.info("'%s' angelernt", name)
        await self.publish_devices()
        await self.publish_device_state(address)
        await self.event("device_added", self.device_info(address))
        return self.device_info(address)

    async def remove_device(self, ident) -> dict:
        address = self.resolve(ident)
        name = self.devices.pop(address)["friendly_name"]
        self.save_devices()
        self.state.pop(address, None)
        self.available.pop(address, None)
        self.last_sync.pop(address, None)
        self._refresh_scan_flags()
        log.info("'%s' entfernt", name)
        await self.clear_device_topics(name)
        await self.publish_devices()
        await self.event("device_removed", {"address": address, "friendly_name": name})
        return {"id": name}

    async def rename_device(self, old, new) -> dict:
        address = self.resolve(old)
        new = self.check_name(new, exclude=address)
        old_name = self.devices[address]["friendly_name"]
        if old_name == new:
            return {"from": old_name, "to": new}
        self.devices[address]["friendly_name"] = new
        self.save_devices()
        self._refresh_scan_flags()
        log.info("'%s' umbenannt in '%s'", old_name, new)
        await self.clear_device_topics(old_name)
        await self.publish_device_state(address)
        await self.publish_devices()
        await self.event("device_renamed", {"from": old_name, "to": new})
        return {"from": old_name, "to": new}

    async def set_options(self, ident, options) -> dict:
        address = self.resolve(ident)
        if not isinstance(options, dict) or not options:
            raise ValueError("options muss ein Objekt sein, z. B. {\"pin\": 123456}")
        unknown = set(options) - {"pin"}
        if unknown:
            raise ValueError(f"Unbekannte Optionen: {', '.join(sorted(unknown))}")
        self.devices[address].setdefault("options", {})["pin"] = self.check_pin(options["pin"])
        self.save_devices()
        log.info("PIN für '%s' geändert", self.devices[address]["friendly_name"])
        self.request_read(address)
        return self.device_info(address)

    async def set_values(self, ident, data) -> dict:
        address = self.resolve(ident)
        driver = DRIVERS[self.devices[address]["type"]]
        changes = driver.parse_set(data)
        log.info("%s: setze %s", self.devices[address]["friendly_name"], changes)
        return await self.run_job(address, changes=changes)

    async def refresh(self, ident) -> dict:
        return await self.run_job(self.resolve(ident))

    # ------------------------------------------------------------ MQTT-Eingang

    async def handle_mqtt(self, topic: str, payload: bytes):
        try:
            await self._handle_mqtt(topic, payload)
        except Exception:
            log.exception("Fehler bei MQTT-Nachricht auf %s", topic)

    async def _handle_mqtt(self, topic: str, payload: bytes):
        rel = topic[len(self.base) + 1:]
        text = payload.decode("utf-8", errors="replace").strip()

        if rel.startswith("bridge/request/"):
            cmd = rel[len("bridge/request/"):]
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = text  # z. B. device/remove mit reinem Namen
            transaction = data.get("transaction") if isinstance(data, dict) else None
            try:
                result = await self.handle_request(cmd, data)
                response = {"data": result, "status": "ok"}
            except (ValueError, NotFound, DeviceError) as e:
                log.warning("Anfrage %s fehlgeschlagen: %s", cmd, e)
                response = {"data": {}, "status": "error", "error": str(e)}
            if transaction is not None:
                response["transaction"] = transaction
            await self.publish(self.topic("bridge", "response", *cmd.split("/")), response)
            return

        parts = rel.split("/")
        if len(parts) < 2 or parts[0] == "bridge":
            return
        name, cmd = parts[0], parts[1]
        try:
            if cmd == "get":
                self.request_read(self.resolve(name))
            elif cmd == "set":
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    raise ValueError(f"Ungültige Payload: {text!r}")
                if len(parts) == 3:
                    data = {parts[2]: data}
                await self.set_values(name, data)
        except (ValueError, NotFound, DeviceError) as e:
            log.warning("%s: %s", rel, e)
            await self.publish(self.topic("bridge", "logging"), {"level": "error", "message": f"{rel}: {e}"})

    async def handle_request(self, cmd: str, data):
        def need(key):
            if not isinstance(data, dict) or key not in data:
                raise ValueError(f"Feld '{key}' fehlt")
            return data[key]

        if cmd == "scan":
            seconds = data.get("time", 15) if isinstance(data, dict) else 15
            return {"devices": await self.scan(seconds)}
        if cmd == "device/add":
            return await self.add_device(need("address"), need("friendly_name"),
                                         data.get("pin", 0), data.get("type"))
        if cmd == "device/remove":
            return await self.remove_device(data if isinstance(data, str) else need("id"))
        if cmd == "device/rename":
            return await self.rename_device(need("from"), need("to"))
        if cmd == "device/options":
            return await self.set_options(need("id"), need("options"))
        raise ValueError(f"Unbekannte Anfrage: {cmd}")


# ---------------------------------------------------------------- MQTT-Verbindung

def _payload_bytes(payload) -> bytes:
    if payload is None:
        return b""
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    return str(payload).encode()


async def mqtt_loop(core: Core):
    import aiomqtt

    m = core.config["mqtt"]
    will = aiomqtt.Will(core.topic("bridge", "state"), json.dumps({"state": "offline"}), qos=1, retain=True)
    tasks: set[asyncio.Task] = set()
    while True:
        try:
            async with aiomqtt.Client(
                hostname=m["server"],
                port=int(m["port"]),
                username=m.get("user") or None,
                password=m.get("password") or None,
                identifier=m.get("client_id") or "bluetooth2mqtt",
                will=will,
            ) as client:
                core.mqtt = client
                log.info("MQTT verbunden mit %s:%s", m["server"], m["port"])
                for sub in (("+", "set"), ("+", "set", "+"), ("+", "get"), ("bridge", "request", "#")):
                    await client.subscribe(core.topic(*sub), qos=1)
                await core.on_mqtt_connected()
                async for msg in client.messages:
                    task = asyncio.create_task(core.handle_mqtt(msg.topic.value, _payload_bytes(msg.payload)))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
        except aiomqtt.MqttError as e:
            log.warning("MQTT nicht verbunden: %s – neuer Versuch in 10 s", e)
        finally:
            core.mqtt = None
        await asyncio.sleep(10)


# ---------------------------------------------------------------- Start

async def amain(args):
    core = Core(Path(args.data))
    if args.mock:
        import mock_ble
        mock_ble.install(core)
        log.warning("MOCK-Modus: es wird kein echtes Bluetooth verwendet")
    log.info("bluetooth2mqtt %s gestartet, %d Geräte angelernt", VERSION, len(core.devices))

    async with asyncio.TaskGroup() as tg:
        tg.create_task(core.worker())
        tg.create_task(core.poller())
        tg.create_task(mqtt_loop(core))
        if core.config["frontend"].get("enabled", True):
            import web
            tg.create_task(web.serve(core))


def main():
    ap = argparse.ArgumentParser(description="bluetooth2mqtt")
    ap.add_argument("--data", default=str(Path(__file__).resolve().parent / "data"),
                    help="Ordner für configuration.json und devices.json")
    ap.add_argument("--mock", action="store_true", help="simulierte Geräte statt Bluetooth (zum Testen)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    LOG_BUFFER.setLevel(logging.INFO)
    logging.getLogger().addHandler(LOG_BUFFER)
    for noisy in ("aiohttp.access", "bleak"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
