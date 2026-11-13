"""MQTT uplink: publishes outbox messages with QoS 1 and removes each only on its PUBACK."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from ..proto import telemetry_pb2 as pb

KIND = {"health": "health", "events": "events", "ota": "ota", "log_line": "log"}


def topic(prefix: str, env: pb.Envelope) -> str:
    return f"{prefix}/{env.device_id}/{KIND[env.WhichOneof('body')]}"


class Uplink:
    def __init__(self, url: str, client_id: str, prefix: str, timeout: float = 5.0):
        u = urlparse(url)
        self.prefix, self.timeout = prefix, timeout
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=False)
        if u.scheme == "mqtts":
            self.c.tls_set()
        if u.username:
            self.c.username_pw_set(u.username, u.password)
        self.host, self.port = u.hostname, u.port or (8883 if u.scheme == "mqtts" else 1883)
        self.c.reconnect_delay_set(1, 120)
        self.started = False

    def connect(self) -> bool:
        try:
            if not self.started:
                self.c.connect(self.host, self.port, keepalive=60)
                self.c.loop_start()
                self.started = True
            deadline = time.monotonic() + self.timeout
            while not self.c.is_connected() and time.monotonic() < deadline:
                time.sleep(0.02)
            return self.c.is_connected()
        except OSError:
            return False

    def flush(self, outbox, batch: int) -> int:
        """Send up to `batch` messages; ack in the outbox only those the broker confirmed."""
        if not self.connect():
            return 0
        pending = []
        for seq, body in outbox.batch(batch):
            env = pb.Envelope.FromString(body)
            pending.append((seq, self.c.publish(topic(self.prefix, env), body, qos=1)))
        done = []
        for seq, info in pending:
            try:
                info.wait_for_publish(self.timeout)
            except (RuntimeError, ValueError):
                break
            if not info.is_published():
                break
            done.append(seq)
        outbox.ack(done)
        return len(done)

    def close(self):
        if self.started:
            self.c.loop_stop()
            self.c.disconnect()
