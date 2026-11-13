# Architecture

## One platform, every device type

A device type is a list of hardware in `config/devices.toml`. The platform builds the hardware layer from
that list and a backend (`linux` on a device, `sim` in tests and the fleet simulation). Applications only
see the interfaces in `src/sfp/hal/base.py`:

| Interface | Linux implementation | What the platform uses it for |
|---|---|---|
| `Modem` | ModemManager, `mmcli -m N -J` | link state and signal for health; never a reason to fail a release |
| `Watchdog` | `/dev/watchdog`, magic close `V` | kicked only while the daemon's loop makes progress |
| `Camera` | V4L2 device in sysfs; frame rate reported by the capture app over IPC | degraded below the configured frame rate |
| `Accelerator` | device node plus hwmon temperature | failing when the node is gone, degraded when hot |

A new board is a new implementation registered with `@implements(kind, backend)`; a new device type is a
new entry in `devices.toml`. Nothing above the interfaces changes. The kernel, drivers and vendor SDKs stay
where they are: the platform is user space only.

## The daemon

`sfp-agent` (systemd `Type=notify`) owns, on every device:

* **Configuration** in four layers (defaults, device type, site, remote). A layer is accepted whole or not
  at all after schema checks, and written with write-fsync-rename plus a directory fsync, so a power cut
  leaves the previous file.
* **Logs** as one JSON object per line, with a rate limit per message so a fault loop cannot fill the LTE
  budget; suppressed lines are counted on the next line through.
* **Health**: memory level and trend (least-squares slope over six hours, O(1) per sample), restarts in
  the last hour, and one check per hardware part.
* **Telemetry**: Protobuf envelopes numbered when produced, kept in a SQLite outbox (WAL) until the broker
  acknowledges them with a QoS 1 PUBACK. When the outbox is full, a health snapshot gives way to a parking
  event, never the other way round.
* **Updates**: see [ota.md](ota.md).
* **IPC**: applications report frame rate and inference health and read configuration over a Unix socket
  with length-prefixed Protobuf frames; a bad request returns an error and never stops the daemon.

## The contract

`src/sfp/proto/telemetry.proto` is the contract between devices and the fleet. Field numbers are never
reused. The generated code is committed and a test regenerates it to catch drift.

## The fleet side

The backend drops repeats by `(device, seq)` and sees gaps. Three consumers read it and nothing else:

* the **rollout controller** (waves per device type and board revision, nightly install window, soak,
  halt on a canary failure or on a failure share);
* **diagnosis** (leak, crash loop, camera worse than its neighbours, an uplink that fails again and again);
* the **dispute desk** (a fine for a missing exit is cancelled if any scanner at the site may have missed
  it: no report, a sequence gap, a restart, a failing part, a dim camera).
