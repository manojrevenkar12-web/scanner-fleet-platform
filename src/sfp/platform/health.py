"""Device health: every hardware component and the platform itself contribute checks; the monitor
turns them into one report with a severity per check.

Memory is judged by its trend as well as its level: a slope fitted over a window catches a leak hours
before the process is killed for running out of memory.
"""

from __future__ import annotations

import collections
from collections.abc import Callable
from dataclasses import dataclass, field

OK, DEGRADED, FAILING = 1, 2, 3
NAMES = {OK: "ok", DEGRADED: "degraded", FAILING: "failing"}


@dataclass
class Check:
    name: str
    severity: int
    value: float
    detail: str = ""


class Slope:
    """Least-squares slope of value over time (units per hour), over a sliding window.

    Running sums keep each update O(1): this runs on every report on small ARM boards."""

    def __init__(self, window_s: float):
        self.window_s = window_s
        self.points: collections.deque[tuple[float, float]] = collections.deque()
        self.origin: float | None = None
        self.n = self.st = self.sv = self.stt = self.stv = 0.0

    def _acc(self, t: float, v: float, sign: int) -> None:
        x = t - self.origin
        self.n += sign
        self.st += sign * x
        self.sv += sign * v
        self.stt += sign * x * x
        self.stv += sign * x * v

    def add(self, t: float, v: float) -> None:
        if self.origin is None:
            self.origin = t
        self.points.append((t, v))
        self._acc(t, v, 1)
        while self.points and t - self.points[0][0] > self.window_s:
            self._acc(*self.points.popleft(), -1)

    def reset(self) -> None:
        self.points.clear()
        self.origin = None
        self.n = self.st = self.sv = self.stt = self.stv = 0.0

    def per_hour(self) -> float:
        if self.n < 3 or self.points[-1][0] - self.points[0][0] < self.window_s / 3:
            return 0.0
        den = self.n * self.stt - self.st * self.st
        return 0.0 if den <= 0 else (self.n * self.stv - self.st * self.sv) / den * 3600


@dataclass
class HealthMonitor:
    cfg: dict                      # config/platform.toml [health]
    memory_limit_mb: float
    restarts: collections.deque = field(default_factory=collections.deque)
    checks: dict[str, Callable[[], Check]] = field(default_factory=dict)

    def __post_init__(self):
        self.memory = Slope(self.cfg["window_minutes"] * 60)

    def register(self, name: str, fn: Callable[[], Check]) -> None:
        self.checks[name] = fn

    def record_restart(self, t: float) -> None:
        self.restarts.append(t)
        self.memory.reset()          # a new process starts a new trend

    def restarts_last_hour(self, t: float) -> int:
        while self.restarts and t - self.restarts[0] > 3600:
            self.restarts.popleft()
        return len(self.restarts)

    def memory_check(self, t: float, rss_mb: float) -> Check:
        self.memory.add(t, rss_mb)
        slope = self.last_slope = self.memory.per_hour()
        if rss_mb > self.cfg["memory_failing_share"] * self.memory_limit_mb:
            return Check("memory", FAILING, rss_mb, f"{rss_mb:.0f} of {self.memory_limit_mb:.0f} MB")
        if slope > self.cfg["memory_leak_mb_per_hour"]:
            return Check("memory", DEGRADED, slope, f"growing {slope:.1f} MB/h")
        return Check("memory", OK, rss_mb)

    def report(self, t: float, rss_mb: float) -> tuple[list[Check], float, int]:
        out = [self.memory_check(t, rss_mb)]
        n = self.restarts_last_hour(t)
        out.append(Check("restarts", FAILING if n >= self.cfg["restarts_failing_per_hour"] else OK, n))
        out += [fn() for fn in self.checks.values()]
        return out, self.last_slope, n

    @staticmethod
    def worst(checks: list[Check]) -> int:
        return max((c.severity for c in checks), default=OK)


def rss_mb(pid: str = "self", proc: str = "/proc") -> float:
    """Resident memory of a process from /proc/<pid>/status (VmRSS, kB)."""
    with open(f"{proc}/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    raise ValueError("no VmRSS line")
