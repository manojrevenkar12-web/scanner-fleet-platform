# AGENTS.md

A Python platform layer for Linux edge devices and the fleet that runs them. Read this first.

## Fast feedback

```bash
pytest                        # about 1 min: platform, hardware, real MQTT broker, small fleets, invariants
ruff check .
python scripts/evaluate.py    # about 6 min: development fleet, every guarantee on, off, and one at a time
python scripts/readme.py      # README.md from reports/
scripts/gen_proto.sh          # after changing telemetry.proto
cd web && npm run build && npm test
```

## Invariants (each has a test)

1. **Nothing that serves reads the truth.** The platform, the hardware layer and the fleet backend,
   rollout, diagnosis, disputes and ingest never import the world or its truth. Only
   `scripts/evaluate.py` compares outcomes with `world.py`.
2. **The world does not read the platform's settings.** `world.py` never reads `platform.toml` or
   `rollout.toml`, so a setting cannot make the faults easier.
3. **Numbered when produced, removed when acknowledged.** A message gets its seq before anything can drop
   it, and leaves the outbox only on a broker acknowledgement.
4. **User space only.** No kernel modules or firmware; hardware through Linux interfaces and vendor SDKs.
5. **Settings in config.** Thresholds, windows, waves and guarantees live in `config/*.toml`.
6. **Generated files match their sources.** `telemetry_pb2.py` from the `.proto`, README and quoted doc
   numbers from `reports/`.
7. **The contract is append-only.** Never reuse or renumber a field in `telemetry.proto`.

## The held-out rule

`config/heldout.toml` is another fleet (seed, board mix, faults, releases). Run it with
`python scripts/evaluate.py --heldout` only after a design is frozen, and report what comes out. Do not
tune anything because of it; make a new held-out fleet instead and say so in the commit. Nothing under
`src/` or `tests/` names it.
