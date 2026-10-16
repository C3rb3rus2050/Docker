"""One serialised application context for the existing SQLite transaction model."""
from __future__ import annotations

import threading
from contextlib import contextmanager

from kest_tool.context import create_context
from kest_tool.fx import FxService


class Runtime:
    def __init__(self, context=None):
        from kest_tool.config import load_env_file
        load_env_file()
        self.context = context or create_context()
        self.lock = threading.RLock()

    @contextmanager
    def use(self):
        # Serialise whole operations, not just individual SQL statements. This
        # preserves duplicate checks / audited writes and SQLite consistency.
        with self.lock:
            yield self.context

    def analysis(self):
        c = self.context
        return {'fx_service': FxService(c.store.base),
                'allow_download': bool(c.settings.get('fx.auto_fetch', True)),
                'ocr_enabled': bool(c.settings.get('pdf.ocr_enabled', False))}

    def close(self):
        self.context.close()
