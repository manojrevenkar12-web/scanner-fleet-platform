"""Parking-fine disputes: before a fine for a missing exit is upheld, check whether the site's scanners
could have missed that exit.

A driver disputes a fine and says when they left. The desk looks at every scanner at the site in a
window around that time: did each one report, was the capture process running without restarts, was
the camera seeing well? If any scanner could have missed the car, the fine is cancelled with that
reason; otherwise it is upheld with the evidence. Code decides from telemetry; the reply text only
reports the decision."""

from __future__ import annotations

from dataclasses import dataclass

from ..platform.health import FAILING


@dataclass
class Decision:
    fine_id: str
    cancel: bool
    reason: str


def decide(fine_id: str, scanners: list[str], claimed_exit: float, backend, cfg: dict, min_fps: float) -> Decision:
    w = cfg["window_minutes"] * 60
    for d in scanners:
        pts = backend.health_between(d, claimed_exit - w, claimed_exit + w)
        if backend.gap_near(d, claimed_exit - w, claimed_exit + w):
            return Decision(fine_id, True, f"messages from scanner {d} around the stated exit never arrived")
        if not pts:
            return Decision(fine_id, True, f"no report from scanner {d} around the stated exit")
        for h in pts:
            if h.restarts > 0:
                return Decision(fine_id, True, f"scanner {d} restarted around that time")
            if any(k != "modem" and v >= FAILING for k, v in h.checks.items()):
                return Decision(fine_id, True, f"scanner {d} reported a failing component")
            if 0 < h.fps < min_fps:
                return Decision(fine_id, True, f"scanner {d} camera at {h.fps:.1f} fps")
    return Decision(fine_id, False, "all scanners at the site were reporting healthy around the stated exit")


def reply(d: Decision) -> str:
    if d.cancel:
        return ("We have cancelled this charge. Our records show a technical issue at the site around the time "
                f"you left ({d.reason}), so we cannot confirm the parking time.")
    return ("We have reviewed your request. All license plate scanners at the site were working normally around "
            "the time you state, and our records show no exit at that time, so the charge stands.")
