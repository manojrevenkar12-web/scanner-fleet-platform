"""Structured logs for devices on a metered uplink: one JSON object per line (journald and the
fleet backend both read it), a per-message rate limit so one fault cannot flood the LTE link, and a
ring buffer of recent lines to attach to a crash report."""

from __future__ import annotations

import collections
import json
import logging
import time


class JsonFormatter(logging.Formatter):
    def __init__(self, device_id: str = "", version: str = ""):
        super().__init__()
        self.device_id, self.version = device_id, version

    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name,
               "msg": record.getMessage(), "device": self.device_id, "version": self.version}
        for k in ("component", "suppressed"):
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, separators=(",", ":"))


class RateLimit(logging.Filter):
    """At most `burst` lines per (logger, message template) per minute. The first line after a quiet
    minute carries how many were suppressed, so nothing is silently lost from the count."""

    def __init__(self, burst: int, clock=time.monotonic):
        super().__init__()
        self.burst, self.clock = burst, clock
        self.window: dict[tuple, list] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        key = (record.name, record.msg)
        now = self.clock()
        start, n, dropped = self.window.get(key, (now, 0, 0))
        if now - start >= 60:
            if dropped:
                record.suppressed = dropped
            start, n, dropped = now, 0, 0
        n += 1
        if n > self.burst:
            self.window[key] = (start, n, dropped + 1)
            return False
        self.window[key] = (start, n, dropped)
        return True


class Ring(logging.Handler):
    def __init__(self, size: int = 200):
        super().__init__()
        self.lines: collections.deque[str] = collections.deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def setup(device_id: str, version: str, burst: int, level: str = "INFO", stream=None) -> Ring:
    root = logging.getLogger("sfp")
    root.handlers.clear()
    root.setLevel(level)
    fmt = JsonFormatter(device_id, version)
    out = logging.StreamHandler(stream)
    ring = Ring()
    for h in (out, ring):
        h.setFormatter(fmt)
        h.addFilter(RateLimit(burst))
        root.addHandler(h)
    root.propagate = False
    return ring
