"""Startpunkt: ``python collector.py`` startet die Oberfläche (siehe ``python collector.py --help``)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from broker_collector.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
