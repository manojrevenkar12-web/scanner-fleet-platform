"""Score the platform on a simulated fleet against what really happened.

Runs the same fleet, faults and releases with every guarantee on, with every guarantee off (the first
version a team would ship), and with each guarantee off in turn. Only this script reads the world's
truth. Writes reports/<world>.json.

    python scripts/evaluate.py               # development fleet, config/fleet.toml
    python scripts/evaluate.py --heldout     # held-out fleet, once, after the design is frozen
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sfp.fleet.diagnose import diagnose  # noqa: E402
from sfp.fleet.disputes import decide  # noqa: E402
from sfp.fleet.sim import FleetSim  # noqa: E402
from sfp.fleet.world import generate, load  # noqa: E402
from sfp.platform import settings  # noqa: E402

KINDS = ("memory_leak", "crash_loop", "camera_degraded", "flaky_uplink")


def fault_truth(world, truth) -> dict[str, dict[str, float]]:
    """kind -> device -> onset, for faults a diagnosis should name."""
    out = {k: {} for k in KINDS}
    for (dev, kind), t in truth.fault_onset.items():
        out[kind][dev] = t
    for d in truth.ran_broken_build:
        out["crash_loop"].setdefault(d, world.start)
    for d in world.devices.values():
        site = world.sites[d.site_id]
        if site.flaky and site.offline:
            out["flaky_uplink"][d.device_id] = site.offline[0][0]
    return out


def score_diagnosis(world, sim, rollout_cfg, found_out: set | None = None) -> dict:
    if not sim.g["fleet_diagnosis"]:
        return {k: {"faults": 0, "found": 0, "false_alarms": 0, "median_hours_to_find": None} for k in KINDS} | {"enabled": False}
    site_of = {d.device_id: d.site_id for d in world.devices.values()}
    issues = diagnose(sim.backend, rollout_cfg["diagnosis"], world.end + 2 * 86400, site_of)
    truth = fault_truth(world, sim.truth)
    out = {"enabled": True}
    for k in KINDS:
        found = {i.device_id: i for i in issues if i.kind == k}
        if found_out is not None:
            found_out.update(d for d in found if d in truth[k])
        real = truth[k]
        hits = [found[d] for d in real if d in found]
        lags = [max(0.0, (i.found_at - real[i.device_id]) / 3600) for i in hits]
        out[k] = {"faults": len(real), "found": len(hits), "false_alarms": len(set(found) - set(real)),
                  "median_hours_to_find": round(statistics.median(lags), 1) if lags else None}
        if k == "memory_leak":
            missed = [sim.truth.leak_rate[d] for d in real if d not in found]
            out[k]["missed_leak_rates_mb_per_h"] = sorted(round(x, 1) for x in missed)
    return out


def score_disputes(world, sim, rollout_cfg) -> dict:
    cfg = world.cfg
    rng = random.Random(cfg["seed"] * 31)
    scanners: dict[str, list[str]] = {}
    for d in world.devices.values():
        if d.device_type == "scanner-arm":
            scanners.setdefault(d.site_id, []).append(d.device_id)
    sim.backend.finalize()
    min_fps = settings.platform()["health"]["min_camera_fps"]
    m = {"fines": len(sim.truth.fines), "wrong_fines": 0, "disputes": 0, "wrong_fines_upheld": 0,
         "wrong_fines_cancelled": 0, "right_fines_upheld": 0, "right_fines_cancelled": 0}
    for fid, site, t, wrong in sim.truth.fines:
        m["wrong_fines"] += wrong
        if rng.random() >= (cfg["dispute_share_wrong"] if wrong else cfg["dispute_share_right"]):
            continue
        m["disputes"] += 1
        claimed = t if wrong else world.start + int((t - world.start) // 86400) * 86400 + rng.uniform(7, 21) * 3600
        if sim.g["dispute_device_check"]:
            cancel = decide(fid, scanners[site], claimed, sim.backend, rollout_cfg["disputes"], min_fps).cancel
        else:
            cancel = False        # today: the record shows no exit, so the charge stands
        key = ("wrong" if wrong else "right") + ("_fines_cancelled" if cancel else "_fines_upheld")
        m[key] += 1
    return m


def score(world, sim, rollout_cfg) -> dict:
    tr, b = sim.truth, sim.backend
    releases = sim.rollout.past + ([sim.rollout.current] if sim.rollout.current else [])
    out = {
        "devices": len(world.devices),
        "availability": round(1 - tr.device_ticks_down / tr.device_ticks, 5),
        "device_hours_down": round(tr.device_ticks_down * world.cfg["tick_minutes"] / 60),
        "max_devices_down_at_once": tr.max_down_at_once,
        "devices_bricked": len(tr.bricked),
        "site_visits": tr.site_visits + sum(1 for d in sim.devs.values() if d.bricked_until is not None),
        "devices_that_ran_the_broken_build": len(tr.ran_broken_build),
        "installs": tr.installs,
        "bundles_refused": {k: len(v) for k, v in sorted(tr.rejected.items())},
        "automatic_rollbacks": tr.rolled_back,
        "on_latest_release_at_end": round(sum(1 for d in sim.devs.values() if d.plat.updater.running_version()
                                              == world.releases()[-1]["version"]) / len(sim.devs), 3),
        "vehicles": tr.vehicles,
        "exits": tr.exits,
        "exits_missed_by_scanners": tr.missed_exits_device - tr.lost_exits_transit,
        "exits_lost_in_transit": tr.lost_exits_transit,
        "messages_received": b.received,
        "duplicates_dropped": b.duplicates,
        "releases": [{"version": r.version, "halted": r.halted, "waves_opened": r.opened,
                      "history": [[round((t - world.start) / 3600, 2), h] for t, h in r.history]} for r in releases],
    }
    out["disputes"] = score_disputes(world, sim, rollout_cfg)
    found: set = set()
    out["diagnosis"] = score_diagnosis(world, sim, rollout_cfg, found)
    faulty = set().union(*fault_truth(world, tr).values())
    # one character per device, in site order, for the dashboard's fleet grid
    states = []
    for d in world.devices:
        if d in tr.bricked:
            states.append("b")          # bricked: waited for a technician
        elif d in tr.ran_broken_build:
            states.append("x")          # ran the broken build, fell back on its own
        elif d in faulty:
            states.append("d" if d in found else "f")   # field fault: named by diagnosis, or not
        else:
            states.append("o")
    out["device_states"] = "".join(states)
    return out


def one(args):
    world_file, name, guarantees = args
    world = generate(load(world_file))
    rollout_cfg = load(ROOT / "config/rollout.toml")
    sim = FleetSim(world, guarantees, rollout_cfg)
    sim.run()
    return name, score(world, sim, rollout_cfg)


def bench() -> dict:
    """How the platform's own code costs on this machine: one health report on a device, and fleet
    ingest of a full day of telemetry from 7,000 scanners."""
    from sfp.fleet.backend import Backend
    from sfp.hal import Hardware
    from sfp.platform.agent import Platform
    from sfp.platform.ota import MemorySlots, Updater
    from sfp.platform.outbox import Outbox

    hw = Hardware(["modem", "watchdog", "camera", "accelerator"], "sim")
    p = Platform("bench", "scanner-arm", hw, Outbox(10**6), Updater(MemorySlots("1.4.0"), "scanner-arm", "arm64", [], 3))
    n = 20000
    t0 = time.perf_counter()
    for i in range(n):
        p.report_health(i * 60.0, 300 + (i % 50))
    per_report_us = (time.perf_counter() - t0) / n * 1e6
    bodies = [body for _, body in p.outbox.batch(96)]
    devices, per_device = 7000, 96
    msgs = []
    for d in range(devices):
        for body in bodies[:per_device]:
            msgs.append(body.replace(b"bench", f"{d:05d}".encode(), 1))
    backend = Backend()
    t0 = time.perf_counter()
    for i, m in enumerate(msgs):
        backend.ingest(m, float(i))
    secs = time.perf_counter() - t0
    return {"health_report_us": round(per_report_us, 1), "ingest_messages": len(msgs),
            "ingest_messages_per_s": round(len(msgs) / secs), "fleet_day_ingest_s": round(secs, 1),
            "message_bytes": len(bodies[0])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heldout", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    world_file = ROOT / ("config/heldout.toml" if a.heldout else "config/fleet.toml")
    out = ROOT / "reports" / ("heldout.json" if a.heldout else "evaluation.json")
    t0 = time.time()
    base = dict(settings.platform()["guarantees"])
    runs = {"platform": base, "first_version": {k: False for k in base}}
    if not a.heldout:
        for k in base:
            runs[f"without_{k}"] = {**base, k: False}
        runs["without_ab_updates_and_staged_rollout"] = {**base, "ab_updates": False, "staged_rollout": False}
    with ProcessPoolExecutor(a.workers) as ex:
        results = dict(ex.map(one, [(str(world_file), n, g) for n, g in runs.items()]))
    for n in runs:
        r = results[n]
        if n not in ("platform", "first_version"):
            r.pop("device_states")
        print(f"{n:32s} availability {r['availability']:.4f}  bricked {r['devices_bricked']:4d}  "
              f"missed exits {r['exits_missed_by_scanners'] + r['exits_lost_in_transit']:7d}  "
              f"wrong fines upheld {r['disputes']['wrong_fines_upheld']:6d}")
    world = generate(load(world_file))
    report = {"world": world.cfg["name"], "seed": world.cfg["seed"], "days": world.cfg["days"],
              "device_sites": [d.site_id for d in world.devices.values()],
              "sites": len(world.sites), "devices": len(world.devices),
              "device_types": {k: sum(1 for d in world.devices.values() if d.device_type == k)
                               for k in sorted({d.device_type for d in world.devices.values()})},
              "releases": [r["version"] for r in world.releases()],
              "runs": {n: results[n] for n in runs}}
    if not a.heldout:
        report["bench_note"] = "bench numbers are machine-dependent and kept out of the reproducible report"
        (ROOT / "reports/bench.json").write_text(json.dumps(bench(), indent=2) + "\n")
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {out.relative_to(ROOT)} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
