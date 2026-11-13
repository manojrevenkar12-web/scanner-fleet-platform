"""Staged OTA rollouts: canary waves across every device type and board revision, each wave soaked
and gated on what the updated devices report. A wave that rolls back or fails more than the allowed
share halts the release. The controller reads the fleet backend only."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def _order(device_id: str, version: str) -> str:
    return hashlib.sha256(f"{version}/{device_id}".encode()).hexdigest()


@dataclass
class Release:
    version: str
    started: float
    waves: list[set[str]]
    opened: int = 0
    opened_at: float = 0.0
    halted: str | None = None
    halted_at: float | None = None
    installed_at: float | None = None
    history: list[tuple[float, str]] = field(default_factory=list)


class Rollout:
    def __init__(self, cfg: dict, inventory: dict[str, tuple[str, str]], staged: bool = True):
        """inventory: device id -> (device type, board revision), as the asset register knows it."""
        self.cfg, self.inventory, self.staged = cfg, inventory, staged
        self.current: Release | None = None
        self.past: list[Release] = []

    def start(self, version: str, t: float) -> Release:
        if self.current:
            self.past.append(self.current)
        if not self.staged:
            waves = [set(self.inventory)]
        else:
            strata: dict[tuple, list[str]] = {}
            for d, key in self.inventory.items():
                strata.setdefault(key, []).append(d)
            waves = [set() for _ in self.cfg["waves"]]
            for members in strata.values():
                members.sort(key=lambda d: _order(d, version))
                done = 0
                for i, share in enumerate(self.cfg["waves"]):
                    upto = max(done + 1, round(share * len(members))) if share < 1 else len(members)
                    waves[i].update(members[done:upto])
                    done = upto
        self.current = Release(version, t, waves, opened=1, opened_at=t)
        self.current.history.append((t, "wave 1 opened"))
        return self.current

    def allowed(self, device_id: str, t: float | None = None) -> str | None:
        r = self.current
        if r is None or r.halted:
            return None
        if t is not None and not self.in_window(device_id, t):
            return None
        return r.version if any(device_id in w for w in r.waves[: r.opened]) else None

    def in_window(self, device_id: str, t: float) -> bool:
        """Each device installs at its own minute inside the nightly window, so a wave never reboots
        a whole site, or the whole fleet, at once."""
        lo, hi = self.cfg["install_hours_utc"]
        hour = (t % 86400) / 3600
        if not lo <= hour < hi:
            return False
        offset = int(_order(device_id, "window")[:8], 16) % int((hi - lo) * 60)
        return hour >= lo + offset / 60

    def _updated(self, backend, r: Release) -> tuple[int, int]:
        bad = updated = 0
        for wave in r.waves[: r.opened]:
            for d in wave:
                dev = backend.devices.get(d)
                if dev is None or r.version not in dev.tried:
                    continue
                updated += 1
                rolled = any(x >= r.started for x in dev.rollbacks)
                bad += rolled or r.version in dev.failing
        return bad, updated

    def step(self, t: float, backend) -> None:
        r = self.current
        if r is None or r.halted or not self.staged:
            return
        bad, updated = self._updated(backend, r)
        canary_failed = r.opened == 1 and bad >= 1      # one rollback in the canary is enough
        if canary_failed or updated >= self.cfg["min_updated_for_gate"] and bad / updated > self.cfg["max_bad_share"]:
            r.halted, r.halted_at = f"{bad} of {updated} updated devices failed or rolled back", t
            r.history.append((t, "halted: " + r.halted))
            return
        open_devices = sum(len(w) for w in r.waves[: r.opened])
        if r.opened < len(r.waves) and updated >= self.cfg["min_installed_share"] * open_devices:
            if r.installed_at is None:
                r.installed_at = t
            if t - r.installed_at >= self.cfg["soak_hours"] * 3600:
                r.opened += 1
                r.opened_at, r.installed_at = t, None
                r.history.append((t, f"wave {r.opened} opened ({updated} devices updated so far)"))
