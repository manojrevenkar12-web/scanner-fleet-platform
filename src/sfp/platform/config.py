"""Layered device configuration: defaults, then device type, then site, then remote.

A later layer overrides an earlier one key by key. Every value is checked against the schema before it
is accepted, so a bad remote push is refused on the device instead of breaking it. The file on disk is
replaced atomically (write, fsync, rename), so a power cut mid-write leaves the old file intact.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LAYERS = ("defaults", "device_type", "site", "remote")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Key:
    kind: type
    default: object
    check: Callable[[object], bool] = lambda v: True
    why: str = ""


SCHEMA: dict[str, Key] = {
    "mqtt.url": Key(str, "mqtt://localhost:1883", lambda v: v.startswith(("mqtt://", "mqtts://")), "mqtt:// or mqtts://"),
    "mqtt.topic_prefix": Key(str, "fleet", lambda v: "/" not in v and "#" not in v and "+" not in v, "no / # +"),
    "telemetry.interval_s": Key(int, 900, lambda v: 10 <= v <= 3600, "10 to 3600"),
    "camera.min_fps": Key(float, 8.0, lambda v: 0 < v <= 60, "0 to 60"),
    "site.id": Key(str, "unassigned", lambda v: 0 < len(v) <= 64, "1 to 64 characters"),
    "log.level": Key(str, "INFO", lambda v: v in ("DEBUG", "INFO", "WARNING", "ERROR"), "a log level"),
    "ota.channel": Key(str, "stable", lambda v: v in ("stable", "canary"), "stable or canary"),
}


@dataclass
class Config:
    path: Path | None = None
    layers: dict[str, dict] = field(default_factory=lambda: {name: {} for name in LAYERS})
    _subscribers: list[Callable[[str, object], None]] = field(default_factory=list)

    def __post_init__(self):
        self.layers["defaults"] = {k: s.default for k, s in SCHEMA.items()}
        if self.path and Path(self.path).exists():
            stored = json.loads(Path(self.path).read_text())
            for name in LAYERS[1:]:
                self.layers[name] = self._validated(stored.get(name, {}))

    @staticmethod
    def _validated(values: dict) -> dict:
        out = {}
        for k, v in values.items():
            if k not in SCHEMA:
                raise ConfigError(f"unknown key {k!r}")
            s = SCHEMA[k]
            if s.kind is float and isinstance(v, int) and not isinstance(v, bool):
                v = float(v)
            if not isinstance(v, s.kind) or isinstance(v, bool) and s.kind is not bool:
                raise ConfigError(f"{k} must be {s.kind.__name__}, got {type(v).__name__}")
            if not s.check(v):
                raise ConfigError(f"{k}={v!r} rejected: {s.why}")
            out[k] = v
        return out

    def get(self, key: str):
        for name in reversed(LAYERS):
            if key in self.layers[name]:
                return self.layers[name][key]
        raise KeyError(key)

    def set_layer(self, name: str, values: dict) -> list[str]:
        """Replace one layer. All-or-nothing: one bad value and nothing changes. Returns changed keys."""
        if name not in LAYERS[1:]:
            raise ConfigError(f"layer {name!r} cannot be set")
        new = self._validated(values)
        before = {k: self.get(k) for k in SCHEMA}
        self.layers[name] = new
        changed = [k for k in SCHEMA if self.get(k) != before[k]]
        if self.path:
            self.save()
        for k in changed:
            for fn in self._subscribers:
                fn(k, self.get(k))
        return changed

    def subscribe(self, fn: Callable[[str, object], None]) -> None:
        self._subscribers.append(fn)

    def effective(self) -> dict:
        return {k: self.get(k) for k in sorted(SCHEMA)}

    def version(self) -> str:
        return hashlib.sha256(json.dumps(self.effective(), sort_keys=True).encode()).hexdigest()[:12]

    def save(self) -> None:
        data = json.dumps({n: self.layers[n] for n in LAYERS[1:]}, sort_keys=True, indent=2).encode()
        atomic_write(Path(self.path), data)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)          # the rename itself survives a power cut
        finally:
            os.close(dfd)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
