"""Device to fleet over a real MQTT broker: QoS 1, nothing removed from the outbox before the broker
confirms it, and an uplink outage that costs no telemetry."""

import time

import pytest

from sfp.fleet.backend import Backend
from sfp.fleet.ingest import Ingest
from sfp.hal import Hardware
from sfp.platform.agent import Platform
from sfp.platform.mqtt import Uplink, topic
from sfp.platform.ota import MemorySlots, Updater
from sfp.platform.outbox import Outbox
from sfp.proto import telemetry_pb2 as pb
from tests.broker import LinkProxy, LocalBroker, external_url


@pytest.fixture
def broker():
    url = external_url()
    if url:
        yield None, url
        return
    b = LocalBroker()
    yield b, b.url
    try:
        b.stop()
    except Exception:  # noqa: BLE001 - already stopped by the test
        pass


def device(name="scanner-1"):
    hw = Hardware(["modem", "watchdog", "camera", "accelerator"], "sim")
    return Platform(name, "scanner-arm", hw, Outbox(500), Updater(MemorySlots("1.4.0"), "scanner-arm", "arm64", [], 3))


def test_telemetry_reaches_the_fleet_once_with_topics_per_kind(broker):
    _, url = broker
    backend = Backend()
    ingest = Ingest(url, backend, client_id=f"ingest-{time.time_ns()}")
    time.sleep(0.5)
    p = device(f"scanner-{time.time_ns() % 10**6}")
    for i in range(5):
        p.record_events(i * 900, 3, 2)
        p.report_health(i * 900, 300 + i)
    up = Uplink(url, p.device_id, "fleet")
    sent = up.flush(p.outbox, 100)
    assert sent == 10 and len(p.outbox) == 0
    assert ingest.wait_for(10)
    d = backend.devices[p.device_id]
    assert d.entries == 15 and d.exits == 10 and len(d.health) == 5 and backend.missing(p.device_id) == 0
    env = pb.Envelope(device_id="x", health=pb.Health())
    assert topic("fleet", env) == "fleet/x/health"
    up.close()
    ingest.close()


def test_an_uplink_outage_costs_no_telemetry(broker):
    _, url = broker
    port = int(url.rsplit(":", 1)[1])
    link = LinkProxy(port)
    backend = Backend()
    ingest = Ingest(url, backend, client_id=f"ingest-{time.time_ns()}")
    time.sleep(0.5)
    p = device(f"scanner-{time.time_ns() % 10**6}")
    up = Uplink(link.url, p.device_id, "fleet", timeout=1.0)
    p.record_events(0, 1, 1)
    assert up.flush(p.outbox, 10) == 1
    link.cut()                                                    # the LTE link drops
    time.sleep(0.3)
    for i in range(1, 4):
        p.record_events(i * 900, 1, 1)
    assert up.flush(p.outbox, 10) == 0 and len(p.outbox) == 3     # nothing confirmed, nothing removed
    link.restore()
    deadline = time.monotonic() + 15
    while len(p.outbox) and time.monotonic() < deadline:          # paho reconnects on its own
        up.flush(p.outbox, 10)
        time.sleep(0.2)
    assert len(p.outbox) == 0 and ingest.wait_for(4)
    assert backend.devices[p.device_id].exits == 4 and backend.missing(p.device_id) == 0
    up.close()
    ingest.close()
    link.close()


def test_unreachable_broker_is_not_an_exception():
    up = Uplink("mqtt://127.0.0.1:9", "x", "fleet", timeout=0.3)
    o = Outbox(5)
    o.put(o.next_seq(), 3, pb.Envelope(device_id="x", events=pb.ParkingEvents()).SerializeToString())
    assert up.flush(o, 5) == 0 and len(o) == 1


def test_the_daemon_runs_end_to_end(broker, tmp_path):
    """The real entry point: SQLite outbox, file slots, sim hardware, a real broker."""
    from sfp.platform.agent import main
    _, url = broker
    backend = Backend()
    ingest = Ingest(url, backend, client_id=f"ingest-{time.time_ns()}")
    time.sleep(0.5)
    name = f"daemon-{time.time_ns() % 10**6}"
    main(["--device-id", name, "--device-type", "gateway-x86", "--hardware", "sim", "--state-dir", str(tmp_path),
          "--mqtt", url, "--interval", "0.05", "--iterations", "3", "--trusted-keys", str(tmp_path / "keys")])
    assert ingest.wait_for(4)
    d = backend.devices[name]
    assert len(d.health) == 3 and d.ota and (tmp_path / "outbox.db").exists() and (tmp_path / "slots/state.json").exists()
    ingest.close()
