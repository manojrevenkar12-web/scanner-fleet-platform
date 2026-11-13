"""The systemd notify protocol, without libsystemd: READY=1 when started, WATCHDOG=1 while healthy.

The platform pings the watchdog only from its main loop and only when that loop is making progress, so
a hung process is restarted by systemd (WatchdogSec in the unit), and a device whose platform stops
entirely is reset by the hardware watchdog.
"""

from __future__ import annotations

import os
import socket


def _address(env: dict) -> str | None:
    addr = env.get("NOTIFY_SOCKET")
    if not addr:
        return None
    return "\0" + addr[1:] if addr.startswith("@") else addr   # abstract namespace


def notify(state: str, env: dict | None = None) -> bool:
    """Send one notification. Returns False when not running under systemd (no socket)."""
    env = os.environ if env is None else env
    addr = _address(env)
    if addr is None:
        return False
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.connect(addr)
        s.sendall(state.encode())
    return True


def watchdog_interval_s(env: dict | None = None) -> float | None:
    """Half the unit's WatchdogSec, as systemd recommends; None if the watchdog is off or not ours."""
    env = os.environ if env is None else env
    usec = env.get("WATCHDOG_USEC")
    pid = env.get("WATCHDOG_PID")
    if not usec or (pid and int(pid) != os.getpid()):
        return None
    return int(usec) / 1e6 / 2
