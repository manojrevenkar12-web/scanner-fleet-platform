"""Write README.md from reports/*.json. Every number in the README comes from these files."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/manojrevenkar12-web/scanner-fleet-platform"
GUARANTEE = {
    "store_and_forward": "Store and forward through uplink outages",
    "ab_updates": "A/B slots with automatic fallback",
    "verify_bundles": "Signed, checked update bundles",
    "staged_rollout": "Staged rollout with canary gate",
    "fleet_diagnosis": "Fleet diagnosis from telemetry",
    "dispute_device_check": "Fine disputes checked against scanner health",
}


def n(x):
    return f"{x:,}"


def pct(x, d=2):
    return f"{x * 100:.{d}f}%"


def render() -> str:
    dev = json.loads((ROOT / "reports/evaluation.json").read_text())
    held = json.loads((ROOT / "reports/heldout.json").read_text())
    bench = json.loads((ROOT / "reports/bench.json").read_text())
    p, f = dev["runs"]["platform"], dev["runs"]["first_version"]
    hp, hf = held["runs"]["platform"], held["runs"]["first_version"]

    def wrong_upheld(r):
        d = r["disputes"]
        return f"{n(d['wrong_fines_upheld'])} of {n(d['wrong_fines_upheld'] + d['wrong_fines_cancelled'])}"

    def right_cancelled(r):
        d = r["disputes"]
        return f"{n(d['right_fines_cancelled'])} of {n(d['right_fines_upheld'] + d['right_fines_cancelled'])}"

    def row(label, fn):
        return f"| {label} | {fn(p)} | {fn(f)} | {fn(hp)} | {fn(hf)} |"

    lines = [
        "# scanner-fleet-platform",
        "",
        "A Python platform layer for a fleet of Linux edge devices, ARM and x86: health monitoring, structured",
        "logging, layered configuration, signed A/B over-the-air updates with automatic fallback, a systemd and",
        "hardware watchdog, MQTT + Protobuf telemetry that waits on the device through LTE outages, and a",
        "hardware abstraction for modems, watchdogs, cameras and AI accelerators. Every device type runs the",
        "same platform; applications build on its interfaces.",
        "",
        "It is built for unattended license-plate scanners on parking sites: thousands of devices outdoors,",
        "on cellular links, where a bad update or a lost exit event turns into a site visit or a wrong",
        "parking fine. A simulated fleet runs the real platform code on every device, with injected faults",
        "(memory leaks, flaky links, a regional outage, crash loops, dirty lenses, rain, damaged downloads, a",
        "build that crashes on one board revision, an image published for the wrong architecture), and scores",
        "the outcome against what really happened.",
        "",
        "![Fleet dashboard](docs/img/dashboard.png)",
        "",
        "## Results",
        "",
        f"Development fleet: {n(dev['devices'])} devices ({n(dev['device_types']['scanner-arm'])} ARM scanners, "
        f"{n(dev['device_types']['gateway-x86'])} x86 gateways) on {n(dev['sites'])} sites, {dev['days']} days, "
        f"releases {' and '.join(dev['releases'])}, seed {dev['seed']}. Held-out fleet: {n(held['devices'])} devices "
        f"on {n(held['sites'])} sites, another board mix, other faults and releases ({', '.join(held['releases'])}), "
        f"seed {held['seed']}, run once after the design was frozen. *First version* is the same code with every "
        "guarantee switched off: send when online, overwrite the running image, push to every device at once.",
        "",
        "| | Platform | First version | Held-out, platform | Held-out, first version |",
        "|---|---:|---:|---:|---:|",
        row("Device availability", lambda r: pct(r["availability"])),
        row("Devices bricked (site visit needed)", lambda r: n(r["devices_bricked"])),
        row("Devices that ran the broken build", lambda r: n(r["devices_that_ran_the_broken_build"])),
        row("Most devices down at once", lambda r: n(r["max_devices_down_at_once"])),
        row("Exit events lost in transit", lambda r: n(r["exits_lost_in_transit"])),
        row("Exits missed by scanners (down, restarting, unreadable)", lambda r: n(r["exits_missed_by_scanners"])),
        row("Disputed wrong fines upheld", wrong_upheld),
        row("Disputed rightful fines cancelled", right_cancelled),
        row("Bundles refused before install", lambda r: n(sum(r["bundles_refused"].values()))),
        row("Automatic rollbacks", lambda r: n(r["automatic_rollbacks"])),
        row("On the latest release at the end", lambda r: pct(r["on_latest_release_at_end"], 1)),
        "",
        "Staged rollouts cost speed: the held-out fix release reached "
        f"{pct(hp['on_latest_release_at_end'], 1)} of the fleet by the end, against "
        f"{pct(hf['on_latest_release_at_end'], 1)} when pushed to everyone at once (which also bricked "
        f"{n(hf['devices_bricked'])} devices). The dispute desk cancels some rightful fines when a scanner at the "
        "site really was unhealthy; that is the price of never upholding a fine the scanner may have caused.",
        "",
        "### What each guarantee is worth",
        "",
        "Same fleet, faults and releases, one guarantee switched off at a time (`config/platform.toml`). They",
        "cover for each other, so the last row switches off the two that together stop a bad release.",
        "",
        "| Switched off | Availability | Bricked | Ran the broken build | Exits lost in transit | Wrong fines upheld | Most down at once |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    names = dict(GUARANTEE)
    names["ab_updates_and_staged_rollout"] = "A/B slots and staged rollout"
    for k, label in names.items():
        r = dev["runs"][f"without_{k}"]
        lines.append(f"| {label} | {pct(r['availability'])} | {n(r['devices_bricked'])} | "
                     f"{n(r['devices_that_ran_the_broken_build'])} | {n(r['exits_lost_in_transit'])} | "
                     f"{n(r['disputes']['wrong_fines_upheld'])} | {n(r['max_devices_down_at_once'])} |")
    lines += [
        "",
        "### Diagnosis from telemetry",
        "",
        "| Fault | Devices (dev) | Found | False alarms | Median hours to find | Held-out: found | Held-out: false alarms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for k, label in (("memory_leak", "Memory leak"), ("crash_loop", "Crash loop"),
                     ("camera_degraded", "Camera degraded (not rain)"), ("flaky_uplink", "Flaky uplink")):
        d, h = p["diagnosis"][k], hp["diagnosis"][k]
        lines.append(f"| {label} | {d['faults']} | {d['found']} | {d['false_alarms']} | {d['median_hours_to_find']} | "
                     f"{h['found']} of {h['faults']} | {h['false_alarms']} |")
    missed = hp["diagnosis"]["memory_leak"].get("missed_leak_rates_mb_per_h", [])
    lines += [
        "",
        "A flaky uplink needs three separate outages before it is named, so one regional outage is not",
        "blamed on a site." + (f" The held-out leak that was missed grows {', '.join(map(str, missed))} MB/h,"
                               " under the 4 MB/h threshold." if missed else ""),
        "",
        "### Cost of the platform itself",
        "",
        f"One health report (all checks, Protobuf envelope, outbox write) takes {bench['health_report_us']} µs on the",
        f"build machine; an envelope is about {bench['message_bytes']} bytes. The fleet backend ingests "
        f"{n(bench['ingest_messages_per_s'])} messages a second in one Python process: a day of 15-minute telemetry",
        f"from 7,000 scanners ({n(bench['ingest_messages'])} messages) in {bench['fleet_day_ingest_s']} s. These two",
        "numbers depend on the machine and are written by the evaluation to `reports/bench.json`.",
        "",
        "## How it works",
        "",
        "```",
        "  application (docker)            platform daemon (sfp-agent, systemd Type=notify)",
        "  plate capture, inference  --IPC (unix socket, protobuf)-->  config  logs  health  OTA updater",
        "                                                                 |                  |",
        "  hardware abstraction: modem (ModemManager)  watchdog (/dev/watchdog)  camera (V4L2)  accelerator",
        "                                                                 |",
        "                     outbox (SQLite, priorities)  --MQTT QoS 1, protobuf-->  fleet backend",
        "                                                                     rollout gate  diagnosis  disputes",
        "```",
        "",
        "* `src/sfp/platform/`: configuration layers with schema checks and atomic writes; JSON logs with a",
        "  rate limit; health monitor with a memory-trend leak check; outbox with priority eviction; A/B",
        "  updater with Ed25519 bundles and boot attempts; sd_notify; IPC; MQTT uplink; the daemon.",
        "* `src/sfp/hal/`: interfaces and the Linux implementations (ModemManager JSON, `/dev/watchdog` with",
        "  magic close, V4L2 in sysfs, accelerator device node and hwmon), plus simulated ones.",
        "* `src/sfp/fleet/`: backend (dedupe, sequence gaps), staged rollout controller, diagnosis rules, the",
        "  parking-fine dispute desk, MQTT ingest, and the simulator (`world.py` holds the truth).",
        "* `deploy/systemd/`: the daemon and capture units (watchdog, restart limits that reboot into the",
        "  bootloader's fallback, hardening); `Dockerfile` builds amd64 and arm64 and runs the tests on each.",
        "* `web/`: the dashboard above, built from the report files.",
        "",
        "Design notes: [architecture](docs/architecture.md), [updates](docs/ota.md),",
        "[field debugging](docs/debugging.md), [decisions](docs/decisions.md).",
        "",
        "## Run it",
        "",
        "```bash",
        "pip install -e '.[dev]'",
        "pytest                                 # platform, hardware, real MQTT broker, fleet, invariants",
        "python scripts/evaluate.py             # development fleet, writes reports/evaluation.json (~6 min)",
        "python scripts/readme.py               # this file, from the reports",
        "docker compose up                      # two devices and Mosquitto",
        "cd web && npm ci && npm run dev        # the dashboard",
        "```",
        "",
        f"Source: {REPO}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    (ROOT / "README.md").write_text(render())
    print("wrote README.md")
