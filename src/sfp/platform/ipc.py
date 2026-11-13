"""IPC between the platform daemon and the applications on the device: a Unix socket, one Protobuf
request and response per call, each framed with a 4-byte length. Applications report health (camera
frame rate, inference latency) and read configuration through it."""

from __future__ import annotations

import os
import socket
import socketserver
import struct
import threading
from collections.abc import Callable

from ..proto import telemetry_pb2 as pb

MAX_FRAME = 1 << 20


def send_frame(sock: socket.socket, data: bytes) -> None:
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock: socket.socket) -> bytes | None:
    head = _exact(sock, 4)
    if head is None:
        return None
    (n,) = struct.unpack(">I", head)
    if n > MAX_FRAME:
        raise ValueError(f"frame of {n} bytes refused")
    return _exact(sock, n)


def _exact(sock, n) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class Server:
    def __init__(self, path: str, handlers: dict[str, Callable[[bytes], bytes]]):
        self.path, self.handlers = path, handlers
        if os.path.exists(path):
            os.unlink(path)
        outer = self

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                while True:
                    try:
                        raw = recv_frame(self.request)
                    except ValueError as e:
                        send_frame(self.request, pb.IpcResponse(ok=False, error=str(e)).SerializeToString())
                        return
                    if raw is None:
                        return
                    req = pb.IpcRequest.FromString(raw)
                    fn = outer.handlers.get(req.method)
                    if fn is None:
                        resp = pb.IpcResponse(ok=False, error=f"unknown method {req.method}")
                    else:
                        try:
                            resp = pb.IpcResponse(ok=True, payload=fn(req.payload))
                        except Exception as e:  # noqa: BLE001 - a bad request must not take the daemon down
                            resp = pb.IpcResponse(ok=False, error=f"{type(e).__name__}: {e}")
                    send_frame(self.request, resp.SerializeToString())

        self.srv = socketserver.ThreadingUnixStreamServer(path, H)
        self.srv.daemon_threads = True
        os.chmod(path, 0o660)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        if os.path.exists(self.path):
            os.unlink(self.path)


class Client:
    def __init__(self, path: str, timeout: float = 2.0):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)

    def call(self, method: str, payload: bytes = b"") -> bytes:
        send_frame(self.sock, pb.IpcRequest(method=method, payload=payload).SerializeToString())
        raw = recv_frame(self.sock)
        if raw is None:
            raise ConnectionError("daemon closed the connection")
        resp = pb.IpcResponse.FromString(raw)
        if not resp.ok:
            raise RuntimeError(resp.error)
        return resp.payload

    def close(self):
        self.sock.close()
