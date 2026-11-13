"""Hardware abstraction: the registry, and the Linux implementations against the files and tools they read."""

import json
import os
from pathlib import Path

import pytest

from sfp.hal import Hardware
from sfp.hal.linux import DeviceNodeAccelerator, LinuxWatchdog, ModemManagerModem, V4L2Camera, parse_mmcli
from sfp.platform.health import DEGRADED, FAILING, OK

FIX = Path(__file__).parent / "fixtures"


def test_every_device_type_builds_on_both_backends():
    from sfp.platform import settings
    for _name, t in settings.load("devices")["types"].items():
        hw = Hardware(t["hardware"], "sim")
        assert set(hw.checks()) <= set(t["hardware"])
    with pytest.raises(KeyError):
        Hardware(["lidar"], "sim")


def test_mmcli_parsing():
    assert parse_mmcli(json.loads((FIX / "mmcli_connected.json").read_text())) == (True, -81)
    assert parse_mmcli(json.loads((FIX / "mmcli_searching.json").read_text())) == (False, -109)


class Proc:
    def __init__(self, code, out):
        self.returncode, self.stdout = code, out


def test_modem_check_from_modemmanager():
    good = (FIX / "mmcli_connected.json").read_text()
    m = ModemManagerModem(run=lambda *a, **k: Proc(0, good))
    assert m.check().severity == OK and m.signal_dbm() == -81
    weak = ModemManagerModem(weak_dbm=-80, run=lambda *a, **k: Proc(0, good))
    assert weak.check().severity == DEGRADED
    gone = ModemManagerModem(run=lambda *a, **k: Proc(1, ""))
    assert gone.check().severity == FAILING and not gone.connected()


def test_watchdog_kicks_and_magic_close(tmp_path):
    dev = tmp_path / "watchdog"
    os.mkfifo(dev)
    r = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    w = LinuxWatchdog(str(dev))
    w.kick()
    w.kick()
    w.close()
    assert os.read(r, 10) == b"kkV"


def test_camera_and_accelerator_from_sysfs(tmp_path):
    v4l = tmp_path / "video4linux" / "video0"
    v4l.mkdir(parents=True)
    (v4l / "name").write_text("imx477 plate cam\n")
    cam = V4L2Camera("imx477", 8.0, str(tmp_path / "video4linux"))
    cam.reported_fps = 15
    assert cam.check().severity == OK
    cam.reported_fps = 3
    assert cam.check().severity == DEGRADED
    assert V4L2Camera("ov5647", 8.0, str(tmp_path / "video4linux")).check().severity == FAILING
    node = tmp_path / "hailo0"
    node.write_text("")
    hw = tmp_path / "hwmon" / "hwmon3"
    hw.mkdir(parents=True)
    (hw / "name").write_text("hailo\n")
    (hw / "temp1_input").write_text("97000\n")
    acc = DeviceNodeAccelerator(str(node), "hailo", 95, str(tmp_path / "hwmon"))
    assert acc.check().severity == DEGRADED and acc.temperature_c() == 97
    assert DeviceNodeAccelerator(str(tmp_path / "missing")).check().severity == FAILING
