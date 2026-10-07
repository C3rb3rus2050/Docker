"""Web-Oberfläche und REST-API für bluetooth2mqtt."""

import hmac
import logging
from pathlib import Path

from aiohttp import web

from errors import DeviceError, NotFound

log = logging.getLogger("bluetooth2mqtt.web")
INDEX = Path(__file__).resolve().parent / "frontend" / "index.html"


def _error(status, message):
    return web.json_response({"error": str(message)}, status=status)


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except NotFound as e:
        return _error(404, e)
    except DeviceError as e:
        return _error(502, e)
    except ValueError as e:
        return _error(400, e)


def make_auth(token: str):
    @web.middleware
    async def auth(request, handler):
        if token and request.path.startswith("/api/"):
            given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(given, token):
                return _error(401, "Token fehlt oder falsch")
        return await handler(request)
    return auth


async def _body(request) -> dict:
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except ValueError:
        raise ValueError("Ungültiges JSON")
    return data if isinstance(data, dict) else {"value": data}


def create_app(core) -> web.Application:
    token = core.config["frontend"].get("auth_token") or ""
    app = web.Application(middlewares=[errors, make_auth(token)])
    r = web.RouteTableDef()

    @r.get("/")
    async def index(request):
        return web.FileResponse(INDEX)

    @r.get("/api/info")
    async def info(request):
        return web.json_response(core.info())

    @r.get("/api/devices")
    async def devices(request):
        return web.json_response([core.device_info(a, full=True) for a in core.devices])

    @r.post("/api/devices")
    async def add(request):
        d = await _body(request)
        return web.json_response(await core.add_device(
            d.get("address", ""), d.get("friendly_name", ""), d.get("pin", 0), d.get("type")))

    @r.delete("/api/devices/{name}")
    async def remove(request):
        return web.json_response(await core.remove_device(request.match_info["name"]))

    @r.post("/api/devices/{name}/rename")
    async def rename(request):
        d = await _body(request)
        return web.json_response(await core.rename_device(request.match_info["name"], d.get("to", "")))

    @r.post("/api/devices/{name}/options")
    async def options(request):
        d = await _body(request)
        return web.json_response(await core.set_options(request.match_info["name"], d))

    @r.post("/api/devices/{name}/set")
    async def set_values(request):
        d = await _body(request)
        data = d["value"] if set(d) == {"value"} else d
        return web.json_response(await core.set_values(request.match_info["name"], data))

    @r.post("/api/devices/{name}/refresh")
    async def refresh(request):
        return web.json_response(await core.refresh(request.match_info["name"]))

    @r.get("/api/scan")
    async def scan_results(request):
        return web.json_response({"running": core.scan_running, "last_scan": core.last_scan,
                                  "devices": core.scan_results})

    @r.post("/api/scan")
    async def scan(request):
        d = await _body(request)
        devices = await core.scan(d.get("time", 15))
        return web.json_response({"running": False, "last_scan": core.last_scan, "devices": devices})

    @r.get("/api/logs")
    async def logs(request):
        return web.json_response(core.logs())

    app.add_routes(r)
    return app


async def serve(core):
    fe = core.config["frontend"]
    runner = web.AppRunner(create_app(core), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, fe.get("host", "0.0.0.0"), int(fe.get("port", 8099)))
    await site.start()
    log.info("Web-Oberfläche läuft auf Port %s", fe.get("port", 8099))
    try:
        import asyncio
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
