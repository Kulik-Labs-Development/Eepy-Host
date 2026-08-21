"""Shared logging setup for Eepy backend.

Extracted from main.py so that every module (auth, mcp_endpoints, etc.) can
import a pre-configured logger without duplicating handler code.
"""

import datetime
import logging
from collections import deque


class MemoryLogHandler(logging.Handler):
    """In-memory ring buffer of recent log lines (served at /superuser/logs)."""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self.buffer: deque = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        log_entry = self.format(record)
        timestamp = datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        self.buffer.append({
            "timestamp": timestamp,
            "level": record.levelname,
            "message": log_entry,
        })


def _build_logger() -> logging.Logger:
    """Create (or return) the shared 'eepy-backend' logger with a memory handler."""
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("eepy-backend")
    if not any(isinstance(h, MemoryLogHandler) for h in log.handlers):
        memory_handler = MemoryLogHandler()
        memory_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        log.addHandler(memory_handler)
    return log


logger = _build_logger()
