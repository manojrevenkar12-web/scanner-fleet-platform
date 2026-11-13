# Over-the-air updates

## Bundle

A manifest (version, device types, architecture, payload SHA-256 and size, minimum base version), an
Ed25519 signature over the manifest bytes, and the payload. The device refuses a bundle when:

| Check | Reason code |
|---|---|
| no trusted key verifies the signature | `signature` |
| payload hash or size differs from the manifest | `payload_hash` |
| device type or architecture not listed | `incompatible` |
| running version older than the manifest's minimum | `needs_newer_base` |
| not newer than what runs | `not_newer` |

## Slots

```
install:  write payload to the slot not running; trying = that slot; attempts = 3
boot:     trying and attempts > 0  -> attempts -= 1, boot trying
          trying and attempts == 0 -> boot the committed slot, result = rolled_back
commit:   the platform, after 30 minutes healthy on the trying slot
```

On hardware the slot state lives in the bootloader environment (U-Boot `bootcount`/`altbootcmd`, or GRUB
`grubenv`), which is how RAUC and Mender do it; `Updater` is written against a three-method slot store so
that backend is a small adapter. The systemd unit's `StartLimitAction=reboot` turns a crash loop on an
uncommitted slot into a reboot, which spends one of the attempts.

## Release

Waves of 2%, 10%, 30% and 100% of every stratum (device type and board revision), so the canary contains
every board. Devices install at their own minute in a nightly window. A wave opens after 80% of the open
waves installed and soaked for six hours. Any rollback or crash loop in the canary halts the release; after
that, more than 5% does.

In the development fleet the broken 1.5.0 ran on 1 device with the canary gate and on 208 without it; with
neither the gate nor A/B slots, those 208 waited for a technician.
