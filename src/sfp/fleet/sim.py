"""Run the platform on every device of a simulated fleet, tick by tick.

Each device runs the real Platform (health monitor, outbox, A/B updater) on simulated hardware. The
world decides what physically happens: links drop, memory leaks, a new build crashes on one board
revision, a download arrives damaged. The fleet side (backend, rollout controller) sees only what the
devices deliver. The same world, seed and faults are used for every setting of the guarantees.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..hal import Hardware
from ..platform import settings
from ..platform.agent import Platform
from ..platform.ota import MemorySlots, Rejected, Updater, build
from ..platform.outbox import Outbox
from .backend import Backend
from .rollout import Rollout
from .world import World, dirty_fps, ts, vehicles

BASE_VERSION = "1.4.0"


@dataclass
class Truth:
    """What really happened, collected for scripts/evaluate.py."""
    vehicles: int = 0
    exits: int = 0
    missed_exits_device: int = 0      # the scanner was down, restarting, or could not read the plate
    lost_exits_transit: int = 0       # recorded, then dropped on the device while offline
    device_ticks_down: int = 0
    device_ticks: int = 0
    bricked: set = field(default_factory=set)
    site_visits: int = 0
    ran_broken_build: set = field(default_factory=set)
    max_down_at_once: int = 0
    installs: int = 0
    rejected: dict = field(default_factory=dict)
    rolled_back: int = 0
    fines: list = field(default_factory=list)          # (fine id, site, time, wrong: bool)
    fault_onset: dict = field(default_factory=dict)    # (device, kind) -> time
    duplicates_sent: int = 0
    leak_rate: dict = field(default_factory=dict)


@dataclass
class Dev:
    truth: object
    plat: Platform
    slot_good: dict
    up_since: float
    down_until: float = 0.0
    bricked_until: float | None = None


class FleetSim:
    def __init__(self, world: World, guarantees: dict, rollout_cfg: dict):
        self.w, self.g = world, guarantees
        self.cfg = settings.platform()
        self.tick_s = world.cfg["tick_minutes"] * 60
        self.rng = random.Random(world.cfg["seed"] * 7919)
        self.backend = Backend()
        self.truth = Truth()
        self.key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.trusted = [self.key.public_key()]
        self.bundles = {}
        self.devs: dict[str, Dev] = {}
        for d in world.devices.values():
            dt = settings.device_type(d.device_type)
            hw = Hardware(dt["hardware"], "sim")
            slots = MemorySlots(BASE_VERSION)
            up = Updater(slots, d.device_type, dt["arch"], self.trusted, self.cfg["ota"]["boot_attempts"],
                         verify=guarantees["verify_bundles"], ab=guarantees["ab_updates"])
            up.boot()
            p = Platform(d.device_id, d.device_type, hw, Outbox(self.cfg["outbox"]["capacity"]), up, guarantees, self.cfg)
            p.started(world.start)
            self.devs[d.device_id] = Dev(d, p, {"a": True, "b": None}, world.start)
        inventory = {d.device_id: (d.device_type, d.hw_rev) for d in world.devices.values()}
        self.rollout = Rollout(rollout_cfg, inventory, staged=guarantees["staged_rollout"])
        self.releases = world.releases()
        self.next_release = 0
        self.fine_seq = 0

    # ------------------------------------------------------------------------------------ releases
    def bundle(self, version: str, device_type: str, wrong_arch: bool):
        key = (version, device_type, wrong_arch)
        if key not in self.bundles:
            payload = random.Random("/".join(map(str, key))).randbytes(4096)
            if wrong_arch:   # the gateway image, published to the scanner channel by mistake
                self.bundles[key] = build(self.key, version, ["gateway-x86"], "amd64", payload)
            else:
                arch = settings.device_type(device_type)["arch"]
                self.bundles[key] = build(self.key, version, [device_type], arch, payload)
        return self.bundles[key]

    def release_for(self, version: str) -> dict:
        return next(r for r in self.releases if r["version"] == version)

    def broken(self, version: str, hw_rev: str) -> bool:
        if version == BASE_VERSION:
            return False
        return hw_rev in self.release_for(version).get("broken_on", [])

    # ------------------------------------------------------------------------------------ devices
    def reboot(self, dev: Dev, t: float) -> None:
        dev.down_until = t + self.w.cfg["reboot_minutes"] * 60
        before = dev.plat.updater.state.last_result
        dev.plat.updater.boot()
        if dev.plat.updater.state.last_result == "rolled_back" and before != "rolled_back":
            self.truth.rolled_back += 1
        dev.plat.started(dev.down_until)
        dev.up_since = dev.down_until

    def try_update(self, dev: Dev, t: float, site_flaky: bool) -> None:
        version = self.rollout.allowed(dev.truth.device_id, t)
        up = dev.plat.updater
        s = up.state
        if version is None or s.trying or s.versions[s.booted] == version or dev.bricked_until:
            return
        if any(v == version for v in s.versions.values()) and s.last_result in ("rolled_back", "reverted"):
            return        # this device already fell back from this version
        rel = self.release_for(version)
        wrong = dev.truth.device_type == "scanner-arm" and "wrong_arch_until" in rel and t < ts(rel["wrong_arch_until"])
        b = self.bundle(version, dev.truth.device_type, wrong)
        corrupt = self.rng.random() < self.w.cfg["faults"]["corrupt_download_share"] * (3 if site_flaky else 1)
        if corrupt:
            b = type(b)(b.manifest, b.signature, b.payload[:-512] + bytes(512))
        try:
            up.install(b)
        except Rejected as e:
            self.truth.rejected.setdefault(e.reason, set()).add(dev.truth.device_id)
            return
        self.truth.installs += 1
        target = up.state.trying or up.state.active
        dev.slot_good[target] = not corrupt and not wrong
        self.reboot(dev, t)

    def step_device(self, dev: Dev, t: float, online: bool, site_flaky: bool) -> tuple[bool, int]:
        """Returns (down this tick, exits the scanner missed)."""
        tr, p = dev.truth, dev.plat
        if p.hw.has("modem"):
            p.hw.modem.up = online
            p.hw.modem.rssi = int(self.rng.uniform(-112, -100)) if site_flaky else int(self.rng.uniform(-95, -75))
        n = vehicles(self.rng, self.w.cfg["vehicles_per_scanner_day"], t, self.tick_s) if tr.device_type == "scanner-arm" else 0
        exits = n // 2 + (n % 2 if self.rng.random() < 0.5 else 0)
        entries = n - exits
        self.truth.vehicles += n
        self.truth.exits += exits

        if dev.bricked_until is not None:
            if t < dev.bricked_until:
                return True, exits
            # a technician reflashed the last good image on site
            s = p.updater.state
            s.versions = {"a": BASE_VERSION, "b": ""}
            s.active = s.booted = "a"
            s.trying, s.last_result = None, "reflashed"
            p.updater.slots.save(s)
            dev.slot_good = {"a": True, "b": None}
            dev.bricked_until = None
            self.truth.site_visits += 1
            p.started(t)
            dev.up_since = t
        if t < dev.down_until:
            return True, exits

        s = p.updater.state
        version = s.versions[s.booted]
        if version != BASE_VERSION and self.broken(version, tr.hw_rev):
            self.truth.ran_broken_build.add(tr.device_id)
        boot_fails = not dev.slot_good.get(s.booted, True) or self.broken(version, tr.hw_rev)
        rss = tr.base_rss
        up_fraction = 1.0
        if boot_fails:
            p.started(t)
            up_fraction = 0.0
            if p.health.restarts_last_hour(t) >= self.cfg["health"]["restarts_failing_per_hour"]:
                if s.trying:                     # an uncommitted slot crash-loops: reboot, let the bootloader decide
                    p.report_health(t, rss)
                    self.reboot(dev, t)
                    return True, exits
                if not self.g["ab_updates"] or not s.trying:
                    dev.bricked_until = t + self.w.cfg["site_visit_hours"] * 3600
                    self.truth.bricked.add(tr.device_id)
                    p.report_health(t, rss)
                    return True, exits
        elif tr.crash_loop_from is not None and t >= tr.crash_loop_from:
            self.truth.fault_onset.setdefault((tr.device_id, "crash_loop"), tr.crash_loop_from)
            p.started(t)
            up_fraction = 0.5
        else:
            if tr.leak_mb_per_h:
                self.truth.fault_onset.setdefault((tr.device_id, "memory_leak"), self.w.start)
                self.truth.leak_rate[tr.device_id] = tr.leak_mb_per_h
            rss = tr.base_rss + tr.leak_mb_per_h * (t - dev.up_since) / 3600
            limit = settings.device_type(tr.device_type)["memory_limit_mb"]
            if rss > limit:                       # the kernel's OOM killer, then systemd restarts the service
                p.started(t)
                dev.up_since = t
                rss = tr.base_rss
                up_fraction = 0.9

        fps = 0.0
        if p.hw.has("camera"):
            fps = dirty_fps(t, tr.dirty_from) * self.w.sites[tr.site_id].fps_factor(t) if up_fraction > 0 else 0.0
            p.hw.camera.frame_rate = fps
            if tr.dirty_from is not None and t >= tr.dirty_from and fps < self.cfg["health"]["min_camera_fps"]:
                self.truth.fault_onset.setdefault((tr.device_id, "camera_degraded"), t)
        unread_share = max(0.0, (self.cfg["health"]["min_camera_fps"] - fps) / self.cfg["health"]["min_camera_fps"] * 0.6) \
            if fps > 0 else 1.0
        rec_exits = sum(1 for _ in range(exits) if self.rng.random() < up_fraction * (1 - unread_share))
        rec_entries = sum(1 for _ in range(entries) if self.rng.random() < up_fraction * (1 - unread_share))
        missed = exits - rec_exits
        if n:
            before = p.dropped_offline
            p.record_events(t, rec_entries, rec_exits, int(n * up_fraction * unread_share))
            if p.dropped_offline > before:
                self.truth.lost_exits_transit += rec_exits
                missed += rec_exits
        p.report_health(t, max(1.0, rss + self.rng.gauss(0, self.w.cfg["faults"]["rss_noise_mb"])))
        p.ota_tick(t)
        return up_fraction < 0.5, missed

    # ------------------------------------------------------------------------------------ run
    def deliver(self, items, t: float, flaky: bool) -> list[int]:
        done = []
        for seq, body in items:
            self.backend.ingest(body, t)
            if flaky and self.rng.random() < self.w.cfg["network"]["lost_ack_share"]:
                self.truth.duplicates_sent += 1
                break                              # the PUBACK was lost: this and the rest go again later
            done.append(seq)
        return done

    def run(self) -> None:
        w, t = self.w, self.w.start
        flaky_sites = {s.site_id for s in w.sites.values() if s.flaky}
        while t < w.end:
            while self.next_release < len(self.releases) and ts(self.releases[self.next_release]["at"]) <= t:
                self.rollout.start(self.releases[self.next_release]["version"], t)
                self.next_release += 1
            down_now = 0
            for dev in self.devs.values():
                site = w.sites[dev.truth.site_id]
                online = site.online(t)
                flaky = site.site_id in flaky_sites
                if online and t >= dev.down_until and dev.bricked_until is None:
                    self.try_update(dev, t, flaky)
                down, missed = self.step_device(dev, t, online, flaky)
                self.truth.missed_exits_device += missed
                self.truth.device_ticks += 1
                self.truth.device_ticks_down += down
                down_now += down
                for _ in range(missed):
                    self.fine_seq += 1
                    self.truth.fines.append((f"F{self.fine_seq}", site.site_id, t + self.rng.uniform(0, self.tick_s), True))
                if online:
                    dev.plat.flush(lambda items, f=flaky, now=t: self.deliver(items, now, f))
            self.truth.max_down_at_once = max(self.truth.max_down_at_once, down_now)
            self.rollout.step(t, self.backend)
            t += self.tick_s
        self._genuine_fines()

    def _genuine_fines(self) -> None:
        share = self.w.cfg["genuine_overstay_share"]
        scanners_per_site: dict[str, int] = {}
        for d in self.w.devices.values():
            if d.device_type == "scanner-arm":
                scanners_per_site[d.site_id] = scanners_per_site.get(d.site_id, 0) + 1
        per_day = self.w.cfg["vehicles_per_scanner_day"] / 2
        for site, n in sorted(scanners_per_site.items()):
            for day in range(self.w.cfg["days"]):
                k = sum(1 for _ in range(int(per_day * n)) if self.rng.random() < share)
                for _ in range(k):
                    self.fine_seq += 1
                    t = self.w.start + day * 86400 + self.rng.uniform(7, 21) * 3600
                    self.truth.fines.append((f"F{self.fine_seq}", site, t, False))
