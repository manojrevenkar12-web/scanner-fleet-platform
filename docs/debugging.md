# Field debugging

What the telemetry already tells you, and the tool for the next step.

| Symptom in the fleet backend | Likely cause | Next step on the device |
|---|---|---|
| `memory_leak`: slope above 4 MB/h for two hours, OOM restarts | leak in the capture process or a library | `tracemalloc` snapshots over IPC for Python; `valgrind --leak-check=full` or `heaptrack` on the native extension; compare `/proc/<pid>/smaps_rollup` over time |
| `crash_loop`: three restarts an hour | config or a native crash | `journalctl -u sfp-capture -b`, `coredumpctl gdb`, `bt full` |
| `flaky_uplink`: repeated outages, outbox depth rising | radio, SIM, APN, operator | `mmcli -m 0 --signal-get`, `tcpdump -i wwan0 port 8883` to see whether TLS completes |
| sequence gaps without an outage | messages refused or evicted | outbox counters in the next health report; broker logs for that client id |
| `camera_degraded` while neighbours are fine | dirt, focus, a dying sensor | frame rate and exposure from the capture app; `v4l2-ctl --all` |
| bundle refused `incompatible` across a wave | wrong image in the channel | stop the release; the canary already did |
