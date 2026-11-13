"""Fleet diagnosis: name what is wrong with a device from its telemetry alone, with the evidence.

Leaks show as a sustained memory slope, crash loops as repeated restarts, a dirty or failing camera as a
low frame rate, and a flaky uplink as telemetry that arrives long after it was observed (the outbox
held it). Each rule needs several points, so one bad sample is not an incident."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Issue:
    device_id: str
    kind: str          # memory_leak | crash_loop | camera_degraded | flaky_uplink
    since: float       # observed time of the first point that made the rule fire
    found_at: float    # when the backend could know: the received time of that point
    evidence: str


def _peer_fps(backend, peers: list[str], t: float, tol: float = 900) -> list[float]:
    vals = []
    for p in peers:
        pts = backend.health_between(p, t - tol, t + tol)
        if pts:
            vals.append(pts[len(pts) // 2].fps)
    return vals


def diagnose(backend, cfg: dict, now: float, site_of: dict[str, str] | None = None,
             exclude_versions: set[str] = frozenset()) -> list[Issue]:
    """site_of: device -> site, from the asset register, so a camera can be compared with its neighbours."""
    out = []
    site_of = site_of or {}
    by_site: dict[str, list[str]] = {}
    for dev, site in site_of.items():
        by_site.setdefault(site, []).append(dev)
    backend.finalize()
    for d in backend.devices.values():
        pts = sorted((h for h in d.health if h.received <= now), key=lambda h: h.t)
        if not pts:
            continue

        def first_run(pred, need, pts=pts):
            run = []
            for h in pts:
                if pred(h):
                    run.append(h)
                    if len(run) >= need:
                        return run[0], max(x.received for x in run)
                else:
                    run = []
            return None

        leak = first_run(lambda h: h.slope > cfg["leak_mb_per_hour"] and h.version not in exclude_versions,
                         cfg["leak_min_points"])
        if leak:
            out.append(Issue(d.device_id, "memory_leak", leak[0].t, leak[1], f"RSS growing {leak[0].slope:.1f} MB/h"))
        crash = first_run(lambda h: h.restarts >= cfg["crash_restarts"] and h.version not in exclude_versions,
                          cfg["crash_min_points"])
        if crash:
            out.append(Issue(d.device_id, "crash_loop", crash[0].t, crash[1], f"{crash[0].restarts} restarts in an hour"))
        peers = [p for p in by_site.get(site_of.get(d.device_id, ""), []) if p != d.device_id
                 and backend.devices.get(p) is not None and backend.devices[p].device_type == d.device_type]

        def camera_low(h, peers=peers):
            if not 0 < h.fps < cfg["camera_min_fps"]:
                return False
            if not peers:
                return True
            others = _peer_fps(backend, peers, h.t)
            return bool(others) and sorted(others)[len(others) // 2] >= cfg["camera_min_fps"]

        cam = first_run(camera_low, cfg["camera_min_points"] if peers else cfg["camera_min_points_alone"])
        if cam:
            out.append(Issue(d.device_id, "camera_degraded", cam[0].t, cam[1], f"{cam[0].fps:.1f} fps"))
        # a flaky uplink is late telemetry again and again; one long outage is an incident, not a site problem
        episodes, run = [], []
        for h in pts:
            if h.received - h.t > cfg["link_delay_minutes"] * 60:
                run.append(h)
                continue
            if len(run) >= cfg["link_min_points"]:
                episodes.append(run)
            run = []
        if len(run) >= cfg["link_min_points"]:
            episodes.append(run)
        if len(episodes) >= cfg["link_min_episodes"]:
            e = episodes[cfg["link_min_episodes"] - 1]
            out.append(Issue(d.device_id, "flaky_uplink", episodes[0][0].t, max(h.received for h in e),
                             f"{len(episodes)} outages with telemetry held on the device"))
    return out
