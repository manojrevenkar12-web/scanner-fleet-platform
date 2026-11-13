"""Linux implementations, through interfaces the kernel and system services already provide:
/dev/watchdog, ModemManager (mmcli -J), V4L2 devices in sysfs, and the accelerator's device node and
hwmon temperature. No kernel code: drivers and SDKs stay where they are."""

from __future__ import annotations

import glob
import json
import os
import subprocess
from pathlib import Path

from ..platform.health import DEGRADED, FAILING, OK, Check
from .base import implements


@implements("watchdog", "linux")
class LinuxWatchdog:
    def __init__(self, path: str = "/dev/watchdog"):
        self.fd = os.open(path, os.O_WRONLY)

    def kick(self) -> None:
        os.write(self.fd, b"k")

    def close(self) -> None:
        os.write(self.fd, b"V")      # magic close: a clean stop does not reset the board
        os.close(self.fd)


def parse_mmcli(doc: dict) -> tuple[bool, int | None]:
    """(connected, signal in dBm) from `mmcli -m <n> -J` (ModemManager 1.20+)."""
    modem = doc.get("modem", {})
    state = modem.get("generic", {}).get("state", "")
    rssi = None
    for tech in ("lte", "5g", "umts", "gsm"):
        val = modem.get("signal", {}).get(tech, {}).get("rssi")
        if val not in (None, "--", ""):
            rssi = int(float(val))
            break
    return state == "connected", rssi


@implements("modem", "linux")
class ModemManagerModem:
    def __init__(self, index: int = 0, weak_dbm: int = -105, run=subprocess.run):
        self.index, self.weak_dbm, self.run = index, weak_dbm, run

    def _status(self) -> tuple[bool, int | None]:
        p = self.run(["mmcli", "-m", str(self.index), "-J"], capture_output=True, text=True, timeout=5)
        if p.returncode != 0:
            return False, None
        return parse_mmcli(json.loads(p.stdout))

    def signal_dbm(self) -> int | None:
        return self._status()[1]

    def connected(self) -> bool:
        return self._status()[0]

    def check(self) -> Check:
        up, rssi = self._status()
        if not up:
            return Check("modem", FAILING, rssi or 0, "not connected")
        if rssi is not None and rssi < self.weak_dbm:
            return Check("modem", DEGRADED, rssi, "weak signal")
        return Check("modem", OK, rssi or 0)


@implements("camera", "linux")
class V4L2Camera:
    """Presence from sysfs; frame rate is reported by the capture application over IPC."""

    def __init__(self, name_contains: str = "", min_fps: float = 8.0, sysfs: str = "/sys/class/video4linux"):
        self.name_contains, self.min_fps, self.sysfs = name_contains, min_fps, sysfs
        self.reported_fps = 0.0

    def present(self) -> bool:
        for d in glob.glob(f"{self.sysfs}/video*"):
            if self.name_contains in Path(d, "name").read_text():
                return True
        return False

    def fps(self) -> float:
        return self.reported_fps

    def check(self) -> Check:
        if not self.present():
            return Check("camera", FAILING, 0, "no video device")
        sev = OK if self.reported_fps >= self.min_fps else DEGRADED
        return Check("camera", sev, self.reported_fps)


@implements("accelerator", "linux")
class DeviceNodeAccelerator:
    """An AI accelerator seen through its device node and hwmon temperature (Hailo, Coral, NPU...)."""

    def __init__(self, node: str = "/dev/hailo0", hwmon_name: str = "", max_c: float = 95.0, sysfs: str = "/sys/class/hwmon"):
        self.node, self.hwmon_name, self.max_c, self.sysfs = node, hwmon_name, max_c, sysfs

    def available(self) -> bool:
        return os.path.exists(self.node)

    def temperature_c(self) -> float | None:
        for d in glob.glob(f"{self.sysfs}/hwmon*"):
            if Path(d, "name").exists() and Path(d, "name").read_text().strip() == self.hwmon_name:
                return int(Path(d, "temp1_input").read_text()) / 1000
        return None

    def check(self) -> Check:
        if not self.available():
            return Check("accelerator", FAILING, 0, f"{self.node} missing")
        t = self.temperature_c()
        if t is not None and t > self.max_c:
            return Check("accelerator", DEGRADED, t, "running hot")
        return Check("accelerator", OK, t or 0)
