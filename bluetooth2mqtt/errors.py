"""Gemeinsame Fehlerklassen."""


class NotFound(Exception):
    """Gerät unbekannt."""


class DeviceError(Exception):
    """Bluetooth-Verbindung fehlgeschlagen."""
