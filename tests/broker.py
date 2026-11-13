"""A real MQTT 3.1.1 broker (amqtt) in a background thread, so tests speak the actual protocol.
Set SFP_MQTT_URL to use an external broker instead (CI runs the same tests against Mosquitto)."""

from __future__ import annotations

import asyncio
import os
import socket
import threading


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalBroker:
    def __init__(self, port: int | None = None):
        from amqtt.broker import Broker
        self.port = port or free_port()
        self.loop = asyncio.new_event_loop()
        cfg = {"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"}},
               "sys_interval": 0, "auth": {"allow-anonymous": True}, "topic-check": {"enabled": False}}
        self.broker = Broker(cfg, loop=self.loop)
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self.broker.start(), self.loop).result(10)

    @property
    def url(self) -> str:
        return f"mqtt://127.0.0.1:{self.port}"

    def stop(self) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.broker.shutdown(), self.loop).result(10)
        except Exception:  # noqa: BLE001 - amqtt can be slow to close idle sessions; the thread is a daemon
            pass


def external_url() -> str | None:
    return os.environ.get("SFP_MQTT_URL")


class LinkProxy:
    """A TCP relay between a device and the broker that can be cut and restored, like an LTE link."""

    def __init__(self, target_port: int):
        self.target = ("127.0.0.1", target_port)
        self.port = free_port()
        self.up = True
        self.conns: list[socket.socket] = []
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", self.port))
        self.srv.listen(16)
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def url(self) -> str:
        return f"mqtt://127.0.0.1:{self.port}"

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            if not self.up:
                c.close()
                continue
            s = socket.create_connection(self.target)
            self.conns += [c, s]
            for a, b in ((c, s), (s, c)):
                threading.Thread(target=self._pipe, args=(a, b), daemon=True).start()

    def _pipe(self, a, b):
        try:
            while True:
                data = a.recv(65536)
                if not data or not self.up:
                    break
                b.sendall(data)
        except OSError:
            pass
        for x in (a, b):
            try:
                x.close()
            except OSError:
                pass

    def cut(self):
        self.up = False
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        self.conns.clear()

    def restore(self):
        self.up = True

    def close(self):
        self.cut()
        self.srv.close()
