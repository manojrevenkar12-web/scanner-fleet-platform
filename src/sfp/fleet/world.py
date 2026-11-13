"""The simulated world: sites, devices, links, faults and releases, with the truth kept apart.

Nothing in the platform or the fleet backend imports this module's truth. The simulation (sim.py)
uses it to decide what physically happens to each device; scripts/evaluate.py alone compares the
outcome with it.
"""

from __future__ import annotations

import random
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

UTC = UTC
HOURLY = [0.1, 0.05, 0.03, 0.03, 0.05, 0.2, 0.6, 1.2, 1.6, 1.7, 1.8, 1.9, 2.0, 1.9, 1.8, 1.9, 2.0, 2.1, 1.9, 1.5,
          1.0, 0.6, 0.35, 0.2]


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def load(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


@dataclass
class Site:
    site_id: str
    region: str
    flaky: bool
    offline: list[tuple[float, float]] = field(default_factory=list)
    rain: list[tuple[float, float, float]] = field(default_factory=list)   # (start, end, fps factor)

    def fps_factor(self, t: float) -> float:
        for a, b, f in self.rain:
            if a <= t < b:
                return f
        return 1.0

    def online(self, t: float) -> bool:
        return not any(a <= t < b for a, b in self.offline)


@dataclass
class DeviceTruth:
    device_id: str
    site_id: str
    device_type: str
    hw_rev: str
    base_rss: float
    leak_mb_per_h: float = 0.0
    dirty_from: float | None = None
    crash_loop_from: float | None = None


@dataclass
class World:
    cfg: dict
    start: float
    end: float
    sites: dict[str, Site]
    devices: dict[str, DeviceTruth]

    def releases(self) -> list[dict]:
        return sorted(self.cfg.get("releases", []), key=lambda r: ts(r["at"]))


def generate(cfg: dict) -> World:
    rng = random.Random(cfg["seed"])
    start = datetime.fromisoformat(cfg["start"]).replace(tzinfo=UTC).timestamp()
    end = start + cfg["days"] * 86400
    net, faults = cfg["network"], cfg["faults"]
    sites, devices = {}, {}
    revs = list(cfg["hardware_revisions"].items())
    ro = net["regional_outage"]
    for i in range(cfg["sites"]):
        s = Site(f"site-{i:04d}", rng.choice(cfg["regions"]), rng.random() < net["flaky_site_share"])
        if s.flaky:
            t = start
            while t < end:
                if rng.random() < net["flaky_outage_per_hour"]:
                    dur = rng.uniform(*net["flaky_outage_hours"]) * 3600
                    s.offline.append((t, t + dur))
                    t += dur
                t += 3600
        for day in range(cfg["days"]):
            if rng.random() < faults["rain_per_site_day"]:
                a = start + day * 86400 + rng.uniform(6, 20) * 3600
                s.rain.append((a, a + rng.uniform(*faults["rain_hours"]) * 3600, rng.uniform(*faults["rain_fps_factor"])))
        if s.region == ro["region"]:
            a = ts(ro["start"])
            s.offline.append((a, a + ro["hours"] * 3600))
        sites[s.site_id] = s
        lo, hi = cfg["scanners_per_site"]
        kinds = ["scanner-arm"] * rng.randint(lo, hi)
        if rng.random() < cfg["gateway_share"]:
            kinds.append("gateway-x86")
        for j, kind in enumerate(kinds):
            rev = rng.choices([r for r, _ in revs], weights=[w for _, w in revs])[0] if kind == "scanner-arm" else "x1"
            d = DeviceTruth(f"{s.site_id}-{j}", s.site_id, kind, rev, cfg["base_rss_mb"][kind] * rng.uniform(0.9, 1.1))
            if kind == "scanner-arm" and rng.random() < faults["leak_share"]:
                d.leak_mb_per_h = rng.uniform(*faults["leak_mb_per_hour"])
            if kind == "scanner-arm" and rng.random() < faults["dirty_camera_share"]:
                d.dirty_from = rng.uniform(start, end - 3 * 86400)
            if rng.random() < faults["crash_loop_share"]:
                d.crash_loop_from = rng.uniform(start + 86400, end - 2 * 86400)
            devices[d.device_id] = d
    return World(cfg, start, end, sites, devices)


def vehicles(rng: random.Random, per_day: float, t: float, tick_s: float) -> int:
    """Vehicles passing one scanner in a tick, by hour of day."""
    hour = int((t % 86400) // 3600)
    mean = per_day * HOURLY[hour] / sum(HOURLY) * tick_s / 3600
    # Poisson by inversion; means here are small
    n, p, u = 0, pow(2.718281828459045, -mean), rng.random()
    s = p
    while u > s and n < 1000:
        n += 1
        p *= mean / n
        s += p
    return n


def dirty_fps(t: float, since: float | None) -> float:
    if since is None or t < since:
        return 15.0
    return max(3.0, 15.0 - (t - since) / 86400 * 5.0)


def iso(t: float) -> str:
    return (datetime.fromtimestamp(t, UTC)).isoformat().replace("+00:00", "Z")


def day_index(t: float, start: float) -> int:
    return int((t - start) // 86400)


__all__ = ["World", "generate", "load", "ts", "vehicles", "dirty_fps", "iso", "day_index", "timedelta"]
