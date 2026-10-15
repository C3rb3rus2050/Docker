"""Launch bundled Streamlit app locally without a console or browser dependency."""
from __future__ import annotations

import os
import socket
import sys
import time
import webbrowser
from pathlib import Path


def root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def writable_dir() -> Path:
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else root()
    target = base / "Daten"
    target.mkdir(parents=True, exist_ok=True)
    return target


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    base = root()
    os.environ["KEST_TOOL_HOME"] = str(writable_dir())
    os.chdir(base)
    from streamlit.web import cli as stcli
    port = free_port()
    sys.argv = [
        "streamlit", "run", str(base / "app.py"),
        "--server.address=127.0.0.1", f"--server.port={port}",
        "--server.headless=true", "--browser.gatherUsageStats=false",
        "--server.enableCORS=true", "--server.enableXsrfProtection=true",
    ]
    # The browser is opened after Streamlit has bound the port.
    import threading
    def open_when_ready():
        for _ in range(120):
            time.sleep(0.5)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    webbrowser.open(f"http://127.0.0.1:{port}")
                    return
            except OSError:
                pass
    threading.Thread(target=open_when_ready, daemon=True).start()
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
