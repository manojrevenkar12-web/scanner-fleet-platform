"""The guarantees on a small fleet, each shown where it matters, scored against the world's truth."""

import pytest

from scripts.evaluate import score
from sfp.fleet.backend import Backend
from sfp.fleet.diagnose import diagnose
from sfp.fleet.disputes import decide, reply
from sfp.fleet.rollout import Rollout
from sfp.fleet.sim import FleetSim
from sfp.proto import telemetry_pb2 as pb
from tests.conftest import small_world


@pytest.fixture(scope="module")
def runs(fleet_cfg, rollout_cfg, guarantees):
    w = small_world(fleet_cfg, sites=40, days=5)
    out = {}
    for name, g in {"platform": guarantees,
                    "first_version": {k: False for k in guarantees},
                    "no_saf": {**guarantees, "store_and_forward": False},
                    "no_staged": {**guarantees, "staged_rollout": False},
                    "no_ab_no_staged": {**guarantees, "staged_rollout": False, "ab_updates": False}}.items():
        sim = FleetSim(w, g, rollout_cfg)
        sim.run()
        out[name] = (sim, score(w, sim, rollout_cfg))
    return w, out


def test_the_platform_bricks_nothing_and_loses_no_exit_in_transit(runs):
    _, r = runs
    m = r["platform"][1]
    assert m["devices_bricked"] == 0 and m["exits_lost_in_transit"] == 0
    assert m["disputes"]["wrong_fines_upheld"] == 0
    first = r["first_version"][1]
    assert first["devices_bricked"] > 0 and first["exits_lost_in_transit"] > 0
    assert first["disputes"]["wrong_fines_upheld"] > 0 and first["availability"] < m["availability"]


def test_a_canary_stops_a_broken_build_before_the_fleet_runs_it(runs):
    _, r = runs
    staged, unstaged = r["platform"][1], r["no_staged"][1]
    assert staged["releases"][0]["halted"]
    assert staged["devices_that_ran_the_broken_build"] < unstaged["devices_that_ran_the_broken_build"]
    # with A/B, even the unstaged fleet falls back on its own; without both, devices wait for a technician
    assert unstaged["devices_bricked"] == 0 and unstaged["automatic_rollbacks"] > 0
    assert r["no_ab_no_staged"][1]["devices_bricked"] > 0


def test_without_store_and_forward_exits_are_lost_but_the_desk_sees_the_gaps(runs):
    _, r = runs
    m = r["no_saf"][1]
    assert m["exits_lost_in_transit"] > 0
    assert m["disputes"]["wrong_fines_cancelled"] > 0


def test_diagnosis_names_injected_faults(runs):
    _, r = runs
    d = r["platform"][1]["diagnosis"]
    for kind in ("memory_leak", "camera_degraded"):
        if d[kind]["faults"]:
            assert d[kind]["found"] >= 0.8 * d[kind]["faults"], kind
    assert r["first_version"][1]["diagnosis"]["enabled"] is False


def test_same_world_same_numbers(fleet_cfg, rollout_cfg, guarantees):
    w = small_world(fleet_cfg, sites=8, days=2)
    a, b = FleetSim(w, guarantees, rollout_cfg), FleetSim(w, guarantees, rollout_cfg)
    a.run()
    b.run()
    assert score(w, a, rollout_cfg) == score(w, b, rollout_cfg)


def test_every_board_revision_is_in_the_canary(rollout_cfg):
    inv = {f"d{i}": ("scanner-arm", "r3" if i < 3 else "r1") for i in range(200)}
    inv.update({f"g{i}": ("gateway-x86", "x1") for i in range(20)})
    r = Rollout(rollout_cfg, inv).start("2.0.0", 0)
    canary = r.waves[0]
    assert any(d.startswith("g") for d in canary) and any(inv[d][1] == "r3" for d in canary)
    assert set().union(*r.waves) == set(inv) and sum(len(w) for w in r.waves) == len(inv)


def test_backend_drops_repeats_and_places_gaps_in_time():
    b = Backend()

    def env(seq, t):
        return pb.Envelope(device_id="d", seq=seq, observed_at_ms=int(t * 1000), health=pb.Health()).SerializeToString()

    for seq, t in ((1, 0), (2, 900), (2, 900), (5, 3600), (6, 4500)):
        b.ingest(env(seq, t), t)
    assert b.duplicates == 1 and b.missing("d") == 2
    assert b.gap_near("d", 1800, 2700) and not b.gap_near("d", 4000, 5000) and b.gap_near("unknown", 0, 1)


def test_dispute_desk_decides_from_telemetry():
    b = Backend()

    def h(t, restarts=0, fps=15.0, cam=1):
        e = pb.Envelope(device_id="s1", seq=int(t // 900) + 1, observed_at_ms=int(t * 1000), device_type="scanner-arm",
                        health=pb.Health(checks=[pb.Check(name="camera", severity=cam), pb.Check(name="modem", severity=3)],
                                         restarts_last_hour=restarts, camera_fps=fps))
        b.ingest(e.SerializeToString(), t)

    for i in range(8):
        h(i * 900, restarts=1 if i == 6 else 0)
    cfg = {"window_minutes": 30}
    ok = decide("F1", ["s1"], 2700, b, cfg, 8.0)
    assert not ok.cancel and "charge stands" in reply(ok)        # a failing modem alone does not cancel a fine
    bad = decide("F2", ["s1"], 5400, b, cfg, 8.0)
    assert bad.cancel and "restarted" in bad.reason and "cancelled" in reply(bad)
    assert decide("F3", ["s1", "s2"], 2700, b, cfg, 8.0).cancel   # s2 never reported


def test_diagnosis_tells_a_dirty_lens_from_rain(rollout_cfg):
    b = Backend()
    seq = {"a": 0, "b": 0}

    def h(dev, t, fps):
        seq[dev] += 1
        b.ingest(pb.Envelope(device_id=dev, seq=seq[dev], observed_at_ms=int(t * 1000), device_type="scanner-arm",
                             health=pb.Health(camera_fps=fps)).SerializeToString(), t)

    for i in range(40):
        h("a", i * 900, 5.0)                       # dirty lens: low while its neighbour is fine
        h("b", i * 900, 15.0 if i < 20 else 6.0)   # rain later at both? only b dips, a stays low
    issues = diagnose(b, rollout_cfg["diagnosis"], 10**9, {"a": "s", "b": "s"})
    kinds = {(i.device_id, i.kind) for i in issues}
    assert ("a", "camera_degraded") in kinds and ("b", "camera_degraded") not in kinds
