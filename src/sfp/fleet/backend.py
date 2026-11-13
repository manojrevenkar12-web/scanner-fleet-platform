"""The fleet backend: what arrives from the devices, and nothing else.

Messages are deduplicated on (device, seq), so a QoS 1 redelivery is counted once, and gaps in seq show
what never arrived. The backend keeps a compact timeline per device (health, events, OTA status) that
the rollout controller, the diagnosis rules and the dispute desk read.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field

from ..proto import telemetry_pb2 as pb


@dataclass
class HealthPoint:
    t: float
    received: float
    worst: int
    rss: float
    slope: float
    restarts: int
    rssi: int
    fps: float
    outbox: int
    version: str
    checks: dict


@dataclass
class Device:
    device_id: str
    device_type: str = ""
    seqs: set = field(default_factory=set)
    seq_times: dict = field(default_factory=dict)  # seq -> observed time, to place gaps in time
    max_seq: int = 0
    health: list[HealthPoint] = field(default_factory=list)
    entries: int = 0
    exits: int = 0
    unread: int = 0
    ota: list = field(default_factory=list)       # (t, slot, version, pending, last_result)
    version: str = ""
    last_seen: float = 0.0
    tried: dict = field(default_factory=dict)      # version -> first time the device reported it installed
    rollbacks: list = field(default_factory=list)  # times the bootloader reported falling back
    failing: dict = field(default_factory=dict)    # version -> first time it crash-looped on it


class Backend:
    def __init__(self):
        self.devices: dict[str, Device] = {}
        self.duplicates = 0
        self.received = 0
        self.events_by_hour: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])

    def ingest(self, body: bytes, received_at: float) -> bool:
        env = pb.Envelope.FromString(body)
        d = self.devices.get(env.device_id)
        if d is None:
            d = self.devices[env.device_id] = Device(env.device_id, env.device_type)
        if env.seq in d.seqs:
            self.duplicates += 1
            return False
        self.received += 1
        d.seqs.add(env.seq)
        d.seq_times[env.seq] = env.observed_at_ms / 1000
        d.max_seq = max(d.max_seq, env.seq)
        t = env.observed_at_ms / 1000
        d.last_seen = max(d.last_seen, received_at)
        d.version = env.software_version
        kind = env.WhichOneof("body")
        if kind == "health":
            h = env.health
            checks = {c.name: c.severity for c in h.checks}
            if checks.get("restarts", 1) >= 3:
                d.failing.setdefault(env.software_version, t)
            d.health.append(HealthPoint(t, received_at, max(checks.values(), default=1), h.memory_rss_mb,
                                        h.memory_slope_mb_per_h, h.restarts_last_hour, h.modem_rssi_dbm, h.camera_fps,
                                        h.outbox_depth, env.software_version, checks))
        elif kind == "events":
            e = env.events
            d.entries += e.entries
            d.exits += e.exits
            d.unread += e.unread_plates
            slot = self.events_by_hour[(env.device_id, int(t // 3600))]
            slot[0] += e.entries
            slot[1] += e.exits
        elif kind == "ota":
            o = env.ota
            d.ota.append((t, o.slot, o.version, o.pending_version, o.last_result))
            for v in (o.version, o.pending_version):
                if v:
                    d.tried.setdefault(v, t)
            if o.last_result == "rolled_back":
                d.rollbacks.append(t)
        return True

    def missing(self, device_id: str) -> int:
        d = self.devices[device_id]
        return d.max_seq - len(d.seqs)

    def gap_near(self, device_id: str, t0: float, t1: float) -> bool:
        """Did any message from this device, produced between t0 and t1, never arrive? A missing seq
        lies between the two received seqs around it; if that span overlaps the window, it counts."""
        d = self.devices.get(device_id)
        if d is None:
            return True
        gaps = getattr(d, "_gaps", None)
        if gaps is None or getattr(d, "_gaps_n", -1) != len(d.seqs):
            order = sorted(d.seqs)
            gaps = d._gaps = [(d.seq_times[x], d.seq_times[y]) for x, y in zip(order, order[1:], strict=False) if y - x > 1]
            if order and order[0] > 1:
                gaps.insert(0, (float("-inf"), d.seq_times[order[0]]))
            d._gaps_n = len(d.seqs)
        return any(a <= t1 and b >= t0 for a, b in gaps)

    def finalize(self) -> None:
        """Order each timeline by observed time (late deliveries arrive out of order)."""
        for d in self.devices.values():
            d.health.sort(key=lambda h: h.t)
            d._times = [h.t for h in d.health]

    def health_between(self, device_id: str, t0: float, t1: float) -> list[HealthPoint]:
        d = self.devices.get(device_id)
        if d is None:
            return []
        times = getattr(d, "_times", None)
        if times is None or len(times) != len(d.health):
            self.finalize()
            times = d._times
        return d.health[bisect.bisect_left(times, t0): bisect.bisect_right(times, t1)]
