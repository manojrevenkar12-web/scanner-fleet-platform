"""The platform layer on its own: configuration, logs, health, outbox, OTA, systemd, IPC."""

import io
import json
import logging
import os
import socket
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sfp.hal import Hardware
from sfp.platform import systemd
from sfp.platform.agent import Platform
from sfp.platform.config import Config, ConfigError
from sfp.platform.health import DEGRADED, FAILING, OK, HealthMonitor, Slope, rss_mb
from sfp.platform.ipc import Client, Server
from sfp.platform.log import RateLimit, setup
from sfp.platform.ota import FileSlots, MemorySlots, Rejected, Updater, build
from sfp.platform.outbox import EVENTS, HEALTH, LOG, Outbox, SqliteStore
from sfp.proto import telemetry_pb2 as pb

KEY = Ed25519PrivateKey.generate()


# ---------------------------------------------------------------------------------------- config
def test_layers_override_in_order_and_survive_a_restart(tmp_path):
    c = Config(tmp_path / "cfg.json")
    c.set_layer("device_type", {"telemetry.interval_s": 300})
    c.set_layer("remote", {"telemetry.interval_s": 60, "camera.min_fps": 10})
    assert c.get("telemetry.interval_s") == 60 and c.get("camera.min_fps") == 10.0
    again = Config(tmp_path / "cfg.json")
    assert again.effective() == c.effective() and again.version() == c.version()


def test_a_bad_remote_push_changes_nothing(tmp_path):
    c = Config(tmp_path / "cfg.json")
    c.set_layer("remote", {"telemetry.interval_s": 120})
    before = (tmp_path / "cfg.json").read_bytes()
    for bad in ({"telemetry.interval_s": 1}, {"telemetry.interval_s": "60"}, {"nope": 1},
                {"telemetry.interval_s": 60, "mqtt.topic_prefix": "a/b"}, {"camera.min_fps": True}):
        with pytest.raises(ConfigError):
            c.set_layer("remote", bad)
    assert c.get("telemetry.interval_s") == 120 and (tmp_path / "cfg.json").read_bytes() == before
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".cfg.json.")]   # no temp files left


def test_subscribers_hear_only_real_changes():
    c, heard = Config(), []
    c.subscribe(lambda k, v: heard.append((k, v)))
    c.set_layer("site", {"site.id": "site-1", "log.level": "INFO"})
    assert heard == [("site.id", "site-1")]


# ---------------------------------------------------------------------------------------- logs
def test_log_lines_are_json_and_floods_are_counted_not_lost():
    out = io.StringIO()
    setup("dev-1", "1.4.0", burst=3, stream=out)
    log = logging.getLogger("sfp.test")
    for _ in range(10):
        log.warning("modem reset")
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert len(lines) == 3 and lines[0]["device"] == "dev-1" and lines[0]["msg"] == "modem reset"
    t = [0.0]
    f = RateLimit(2, clock=lambda: t[0])
    rec = logging.LogRecord("x", logging.INFO, "", 0, "m", None, None)
    assert [f.filter(rec) for _ in range(5)] == [True, True, False, False, False]
    t[0] = 61
    rec2 = logging.LogRecord("x", logging.INFO, "", 0, "m", None, None)
    assert f.filter(rec2) and rec2.suppressed == 3


# ---------------------------------------------------------------------------------------- health
def test_slope_finds_a_leak_and_ignores_a_flat_line():
    s = Slope(3600 * 6)
    for i in range(30):
        s.add(i * 900, 300 + 2.5 * i)              # 10 MB/h
    assert abs(s.per_hour() - 10) < 1e-6
    flat = Slope(3600 * 6)
    for i in range(30):
        flat.add(i * 900, 300 + (5 if i % 2 else -5))
    assert abs(flat.per_hour()) < 1


def test_memory_check_levels(tmp_path):
    cfg = {"window_minutes": 360, "memory_leak_mb_per_hour": 4, "memory_failing_share": 0.9,
           "restarts_failing_per_hour": 3}
    m = HealthMonitor(cfg, 900)
    assert m.memory_check(0, 300).severity == OK
    assert m.memory_check(1, 850).severity == FAILING
    for i in range(3):
        m.record_restart(100 + i)
    checks, _, n = m.report(200, 300)
    assert n == 3 and HealthMonitor.worst(checks) == FAILING
    status = tmp_path / "1" / "status"
    status.parent.mkdir()
    status.write_text("Name:\tx\nVmRSS:\t  204800 kB\n")
    assert rss_mb("1", str(tmp_path)) == 200


def test_a_weak_link_degrades_but_does_not_fail_the_device():
    hw = Hardware(["modem", "watchdog", "camera", "accelerator"], "sim")
    p = Platform("d", "scanner-arm", hw, Outbox(10), Updater(MemorySlots("1.4.0"), "scanner-arm", "arm64", [], 3))
    hw.modem.rssi = -110
    hw.modem.up = False
    assert p.report_health(0, 300) == OK
    hw.camera.frame_rate = 5
    assert p.report_health(900, 300) == DEGRADED


# ---------------------------------------------------------------------------------------- outbox
def test_outbox_keeps_parking_events_over_health_when_full(tmp_path):
    for store in (None, SqliteStore(str(tmp_path / "o.db"))):
        o = Outbox(4, store)
        for prio in (HEALTH, LOG, HEALTH, EVENTS):
            o.put(o.next_seq(), prio, b"x")
        assert o.put(o.next_seq(), EVENTS, b"e")           # evicts the log line first
        assert o.put(o.next_seq(), EVENTS, b"e")           # then the oldest health snapshot
        assert o.stats.evicted == 2
        assert o.put(o.next_seq(), EVENTS, b"e") and o.stats.evicted == 3      # the last health snapshot goes
        assert not o.put(o.next_seq(), HEALTH, b"h") and o.stats.refused == 1  # nothing below health is left
        seqs = [s for s, _ in o.batch(10)]
        o.ack(seqs[:2])
        assert len(o) == 2


def test_sqlite_outbox_survives_a_reboot(tmp_path):
    path = str(tmp_path / "o.db")
    o = Outbox(10, SqliteStore(path))
    for _ in range(3):
        o.put(o.next_seq(), EVENTS, b"e")
    del o
    again = Outbox(10, SqliteStore(path))
    assert len(again) == 3 and again.next_seq() == 4
    assert sqlite3.connect(path).execute("pragma journal_mode").fetchone()[0] == "wal"


def test_store_and_forward_off_drops_offline_messages_but_numbers_them():
    hw = Hardware(["modem", "watchdog"], "sim")
    g = {"store_and_forward": False}
    p = Platform("g", "gateway-x86", hw, Outbox(10), Updater(MemorySlots("1.4.0"), "gateway-x86", "amd64", [], 3), g)
    hw.modem.up = False
    p.report_health(0, 500)
    hw.modem.up = True
    p.report_health(900, 500)
    (seq, body), = p.outbox.batch(5)
    assert seq == 2 and p.dropped_offline == 1 and pb.Envelope.FromString(body).seq == 2


# ---------------------------------------------------------------------------------------- OTA
def bundle(version, types=("scanner-arm",), arch="arm64", key=KEY, payload=b"rootfs" * 100, min_version="0.0.0"):
    return build(key, version, types, arch, payload, min_version)


def updater(tmp_path=None, version="1.4.0", **kw):
    slots = FileSlots(tmp_path) if tmp_path else MemorySlots(version)
    if tmp_path:
        s = slots.load()
        s.versions = {"a": version, "b": ""}
        slots.save(s)
    return Updater(slots, "scanner-arm", "arm64", [KEY.public_key()], 3, **kw)


@pytest.mark.parametrize("b,reason", [
    (bundle("1.5.0", key=Ed25519PrivateKey.generate()), "signature"),
    (bundle("1.5.0", types=("gateway-x86",), arch="amd64"), "incompatible"),
    (bundle("1.4.0"), "not_newer"),
    (bundle("1.5.0", min_version="1.4.5"), "needs_newer_base"),
])
def test_bundles_that_do_not_check_out_are_refused(b, reason):
    with pytest.raises(Rejected) as e:
        updater().install(b)
    assert e.value.reason == reason


def test_a_damaged_payload_is_refused():
    b = bundle("1.5.0")
    with pytest.raises(Rejected) as e:
        updater().install(type(b)(b.manifest, b.signature, b.payload[:-1] + b"X"))
    assert e.value.reason == "payload_hash"


def test_new_slot_commits_only_when_healthy_and_falls_back_on_its_own(tmp_path):
    u = updater(tmp_path)
    u.install(bundle("1.5.0"))
    assert (tmp_path / "slot-b.img").exists()
    assert u.boot() == "b" and u.state.attempts_left == 2
    assert u.boot() == "b" and u.boot() == "b"
    assert u.boot() == "a" and u.state.last_result == "rolled_back" and u.running_version() == "1.4.0"
    u.install(bundle("1.5.1"))
    assert u.boot() == "b" and u.commit() and u.state.active == "b" and u.boot() == "b"
    assert u.revert() and u.running_version() == "1.4.0"


def test_without_ab_the_running_slot_is_overwritten():
    u = updater(ab=False)
    u.install(bundle("1.5.0"))
    assert u.state.trying is None and u.boot() == "a" and u.running_version() == "1.5.0"


def test_platform_commits_after_the_health_window():
    hw = Hardware(["modem", "watchdog", "camera", "accelerator"], "sim")
    u = updater()
    p = Platform("d", "scanner-arm", hw, Outbox(100), u)
    u.install(bundle("1.5.0"))
    u.boot()
    p.started(0)
    for i in range(4):
        p.report_health(i * 600, 300)
        p.ota_tick(i * 600)
    assert u.state.active == "b" and u.state.last_result == "committed"
    statuses = [pb.Envelope.FromString(b).ota for _, b in p.outbox.batch(100) if pb.Envelope.FromString(b).HasField("ota")]
    assert statuses[0].pending_version == "1.5.0" and statuses[-1].last_result == "committed"


# ---------------------------------------------------------------------------------------- systemd, IPC
def test_sd_notify_reaches_the_socket(tmp_path):
    path = str(tmp_path / "notify")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(path)
    assert systemd.notify("READY=1", {"NOTIFY_SOCKET": path})
    assert srv.recv(64) == b"READY=1"
    assert not systemd.notify("READY=1", {})
    assert systemd.watchdog_interval_s({"WATCHDOG_USEC": "20000000", "WATCHDOG_PID": str(os.getpid())}) == 10
    assert systemd.watchdog_interval_s({"WATCHDOG_USEC": "20000000", "WATCHDOG_PID": "1"}) is None


def test_ipc_round_trip_errors_and_oversized_frames(tmp_path):
    path = str(tmp_path / "sfp.sock")
    srv = Server(path, {"echo": lambda b: b[::-1], "boom": lambda b: 1 / 0})
    try:
        c = Client(path)
        assert c.call("echo", b"abc") == b"cba"
        with pytest.raises(RuntimeError, match="ZeroDivisionError"):
            c.call("boom")
        with pytest.raises(RuntimeError, match="unknown method"):
            c.call("nope")
        assert c.call("echo", b"still alive") == b"evila llits"
        c.close()
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.connect(path)
        raw.sendall((2**30).to_bytes(4, "big"))
        assert b"refused" in raw.recv(200)
    finally:
        srv.close()
