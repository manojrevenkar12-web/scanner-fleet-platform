"""The platform daemon on each device: collects health from the platform and every hardware part,
records the application's parking events, keeps telemetry in the outbox until the broker confirms it,
commits or abandons a new OS slot by its health, and pings the watchdog only while all of that runs.

The same class runs on a real device (Linux hardware, MQTT, systemd) and inside the fleet simulation
(simulated hardware and clock), so the simulation measures the code that ships.
"""

from __future__ import annotations

import argparse
import logging
import time

from ..hal import Hardware
from ..proto import telemetry_pb2 as pb
from . import settings, systemd
from .health import FAILING, OK, HealthMonitor
from .outbox import EVENTS, HEALTH, OTA, Outbox

log = logging.getLogger("sfp.agent")


class Platform:
    def __init__(self, device_id: str, device_type: str, hardware: Hardware, outbox: Outbox, updater,
                 guarantees: dict | None = None, cfg: dict | None = None):
        cfg = cfg or settings.platform()
        self.cfg = cfg
        self.g = guarantees or cfg["guarantees"]
        self.device_id, self.device_type = device_id, device_type
        self.hw, self.outbox, self.updater = hardware, outbox, updater
        self.health = HealthMonitor(cfg["health"], settings.device_type(device_type)["memory_limit_mb"])
        for name, fn in hardware.checks().items():
            self.health.register(name, fn)
        self.healthy_since: float | None = None
        self.last_ota = ""
        self.dropped_offline = 0

    # -------------------------------------------------------------------------------- telemetry
    def _put(self, t: float, prio: int, **body) -> None:
        seq = self.outbox.next_seq()          # numbered when produced: anything lost shows as a gap
        if not self.g["store_and_forward"] and not self.link_up():
            self.dropped_offline += 1
            return
        env = pb.Envelope(device_id=self.device_id, seq=seq, observed_at_ms=int(t * 1000),
                          device_type=self.device_type, software_version=self.updater.running_version(), **body)
        self.outbox.put(seq, prio, env.SerializeToString())

    def link_up(self) -> bool:
        return self.hw.modem.connected() if self.hw.has("modem") else True

    def record_events(self, t: float, entries: int, exits: int, unread: int = 0) -> None:
        self._put(t, EVENTS, events=pb.ParkingEvents(entries=entries, exits=exits, unread_plates=unread))

    def report_health(self, t: float, rss_mb: float) -> int:
        checks, slope, restarts = self.health.report(t, rss_mb)
        h = pb.Health(checks=[pb.Check(name=c.name, severity=c.severity, value=c.value, detail=c.detail) for c in checks],
                      memory_rss_mb=rss_mb, memory_slope_mb_per_h=slope, restarts_last_hour=restarts,
                      outbox_depth=len(self.outbox))
        if self.hw.has("modem"):
            h.modem_rssi_dbm = self.hw.modem.signal_dbm() or 0
        if self.hw.has("camera"):
            h.camera_fps = self.hw.camera.fps()
        self._put(t, HEALTH, health=h)
        worst = HealthMonitor.worst([c for c in checks if c.name != "modem"])  # a weak link is not a bad build
        if worst >= FAILING:
            self.healthy_since = None
        elif self.healthy_since is None:
            self.healthy_since = t
        return worst

    # -------------------------------------------------------------------------------- lifecycle
    def started(self, t: float) -> None:
        """The application (re)started: count it, and restart the health gate for a new slot."""
        self.health.record_restart(t)
        self.healthy_since = None

    def ota_tick(self, t: float) -> None:
        s = self.updater.state
        if s.trying and s.booted == s.trying and self.healthy_since is not None and \
                t - self.healthy_since >= self.cfg["ota"]["healthy_minutes_to_commit"] * 60:
            self.updater.commit()
            log.info("committed slot %s", s.booted)
        s = self.updater.state
        status = f"{s.booted}/{s.versions[s.booted]}/{s.trying}/{s.last_result}"
        if status != self.last_ota:
            self.last_ota = status
            self._put(t, OTA, ota=pb.OtaStatus(slot=s.booted, version=s.versions[s.booted],
                                               pending_version=s.versions.get(s.trying, "") if s.trying else "",
                                               boot_attempts_left=s.attempts_left, last_result=s.last_result))

    def flush(self, send, batch: int | None = None) -> int:
        """send(list of (seq, bytes)) -> list of confirmed seqs."""
        if not self.link_up() or len(self.outbox) == 0:
            return 0
        items = self.outbox.batch(batch or self.cfg["outbox"]["batch"])
        done = send(items)
        self.outbox.ack(done)
        return len(done)


# ------------------------------------------------------------------------------------ real device
def trusted_keys(directory: str) -> list:
    """Ed25519 public keys (PEM) that may sign update bundles, one file each."""
    from pathlib import Path

    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    d = Path(directory)
    return [load_pem_public_key(p.read_bytes()) for p in sorted(d.glob("*.pem"))] if d.is_dir() else []


def main(argv=None) -> None:
    from . import log as logsetup
    from .health import rss_mb
    from .mqtt import Uplink
    from .ota import FileSlots, Updater
    from .outbox import SqliteStore

    ap = argparse.ArgumentParser(description="Platform daemon for one device")
    ap.add_argument("--device-id", required=True)
    ap.add_argument("--device-type", required=True)
    ap.add_argument("--hardware", choices=["linux", "sim"], default="linux")
    ap.add_argument("--state-dir", default="/var/lib/sfp")
    ap.add_argument("--mqtt", default="mqtt://localhost:1883")
    ap.add_argument("--trusted-keys", default="/etc/sfp/keys")
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--iterations", type=int, default=0, help="stop after this many loops (0: run forever)")
    a = ap.parse_args(argv)

    cfg = settings.platform()
    dt = settings.device_type(a.device_type)
    logsetup.setup(a.device_id, "dev", cfg["log"]["burst"])
    hw = Hardware(dt["hardware"], a.hardware)
    updater = Updater(FileSlots(f"{a.state_dir}/slots"), a.device_type, dt["arch"], trusted_keys(a.trusted_keys),
                      cfg["ota"]["boot_attempts"])
    updater.boot()
    outbox = Outbox(cfg["outbox"]["capacity"], SqliteStore(f"{a.state_dir}/outbox.db"))
    p = Platform(a.device_id, a.device_type, hw, outbox, updater)
    up = Uplink(a.mqtt, a.device_id, "fleet")
    p.started(time.time())
    systemd.notify("READY=1")
    n = 0
    while True:
        t = time.time()
        worst = p.report_health(t, rss_mb())
        p.ota_tick(t)
        sent = up.flush(outbox, cfg["outbox"]["batch"]) if p.link_up() else 0
        if worst < FAILING:
            if hw.has("watchdog"):
                hw.watchdog.kick()
            systemd.notify("WATCHDOG=1")
        systemd.notify(f"STATUS=health {'ok' if worst == OK else worst}, outbox {len(outbox)}, sent {sent}")
        n += 1
        if a.iterations and n >= a.iterations:
            break
        time.sleep(a.interval)
    up.close()


if __name__ == "__main__":  # pragma: no cover
    main()
