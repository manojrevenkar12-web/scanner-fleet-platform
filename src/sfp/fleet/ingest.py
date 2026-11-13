"""The fleet side of MQTT: subscribe to every device's telemetry and feed the backend."""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from .backend import Backend


class Ingest:
    def __init__(self, url: str, backend: Backend, prefix: str = "fleet", client_id: str = "fleet-ingest"):
        u = urlparse(url)
        self.backend, self.prefix = backend, prefix
        self.lock = threading.Lock()
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=False)
        if u.username:
            self.c.username_pw_set(u.username, u.password)
        self.c.on_connect = lambda c, *_: c.subscribe(f"{prefix}/+/+", qos=1)
        self.c.on_message = self._on_message
        self.c.connect(u.hostname, u.port or 1883, keepalive=30)
        self.c.loop_start()

    def _on_message(self, client, userdata, msg) -> None:
        with self.lock:
            self.backend.ingest(msg.payload, time.time())

    def wait_for(self, n: int, timeout: float = 10) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.backend.received + self.backend.duplicates >= n:
                return True
            time.sleep(0.05)
        return False

    def close(self) -> None:
        self.c.loop_stop()
        self.c.disconnect()
