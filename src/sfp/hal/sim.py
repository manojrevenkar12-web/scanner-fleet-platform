"""Simulated hardware with the same interfaces, for tests and the fleet simulation. Each part exposes
plain attributes the simulation sets (signal, link up, frame rate)."""

from __future__ import annotations

from ..platform.health import DEGRADED, FAILING, OK, Check
from .base import implements


@implements("modem", "sim")
class SimModem:
    def __init__(self, rssi: int = -80, up: bool = True, weak_dbm: int = -105):
        self.rssi, self.up, self.weak_dbm = rssi, up, weak_dbm

    def signal_dbm(self) -> int | None:
        return self.rssi

    def connected(self) -> bool:
        return self.up

    def check(self) -> Check:
        if not self.up:
            return Check("modem", FAILING, self.rssi, "not connected")
        return Check("modem", DEGRADED if self.rssi < self.weak_dbm else OK, self.rssi)


@implements("watchdog", "sim")
class SimWatchdog:
    def __init__(self):
        self.kicks = 0
        self.closed = False

    def kick(self) -> None:
        self.kicks += 1

    def close(self) -> None:
        self.closed = True


@implements("camera", "sim")
class SimCamera:
    def __init__(self, frame_rate: float = 15.0, min_fps: float = 8.0):
        self.frame_rate, self.min_fps = frame_rate, min_fps

    def fps(self) -> float:
        return self.frame_rate

    def check(self) -> Check:
        if self.frame_rate <= 0:
            return Check("camera", FAILING, 0, "no frames")
        return Check("camera", OK if self.frame_rate >= self.min_fps else DEGRADED, self.frame_rate)


@implements("accelerator", "sim")
class SimAccelerator:
    def __init__(self, ok: bool = True):
        self.ok = ok

    def available(self) -> bool:
        return self.ok

    def check(self) -> Check:
        return Check("accelerator", OK if self.ok else FAILING, 1 if self.ok else 0)
