# Decisions

**User space only.** The platform talks to hardware through what Linux and the vendor SDKs already
expose (ModemManager, `/dev/watchdog`, V4L2, device nodes, hwmon). Kernel and firmware work stays with the
board support package; the platform stays portable between ARM and x86.

**Numbered when produced, removed when acknowledged.** A message gets its sequence number before anything
can drop it, so a loss is visible as a gap at the backend, and it leaves the device only on a PUBACK.
Without store and forward the development fleet lost 23,721 exit events in transit.

**Priorities in the outbox.** A long outage costs health history before it costs billing data.

**A/B slots and a canary, both.** Either one alone saved the fleet in the simulation; with neither, 208
devices were bricked by one release. A wrong-architecture image, a damaged download and a build that
crashes on one board are different failures, and the layers catch different ones.

**Stratified canaries.** In the held-out fleet the broken board is one in ten; a canary drawn from the
whole fleet can miss it, one drawn from every board revision cannot.

**Neighbours, not thresholds, for cameras.** Rain dims every camera at a site; dirt dims one. Comparing a
scanner with the others at its site removed the false alarms a plain frame-rate threshold raised.

**Code decides disputes.** A fine is cancelled when telemetry says a scanner could have missed the exit,
and the reply says so; otherwise it stands with the evidence. In the development fleet the desk upheld 0
of 4,582 disputed wrong fines and cancelled 62 of 916 disputed rightful ones.
