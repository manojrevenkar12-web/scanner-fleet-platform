"""Rules a test can hold: nothing on the device or the fleet side reads the world's truth, the world
does not read the platform's settings, tunable numbers live in config, generated files match their
sources, and the held-out fleet is named only by the evaluation."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVING = ["src/sfp/platform", "src/sfp/hal", "src/sfp/fleet/backend.py", "src/sfp/fleet/rollout.py",
           "src/sfp/fleet/diagnose.py", "src/sfp/fleet/disputes.py", "src/sfp/fleet/ingest.py"]


def files(paths):
    for p in paths:
        p = ROOT / p
        yield from (p.rglob("*.py") if p.is_dir() else [p])


def test_nothing_that_serves_reads_the_truth():
    for f in files(SERVING):
        text = f.read_text()
        assert "world" not in text.lower().replace("hello world", ""), f
        assert "truth" not in text, f


def test_the_world_does_not_read_platform_settings():
    text = (ROOT / "src/sfp/fleet/world.py").read_text()
    assert "settings" not in text and "platform.toml" not in text and "rollout.toml" not in text


def test_tunable_numbers_live_in_config():
    code = "".join(f.read_text() for f in files(["src/sfp/platform/agent.py", "src/sfp/fleet/rollout.py",
                                                 "src/sfp/fleet/diagnose.py"]))
    for key in ("healthy_minutes_to_commit", "capacity", "max_bad_share", "soak_hours", "leak_mb_per_hour",
                "camera_min_points", "link_min_episodes"):
        assert f'["{key}"]' in code, key
    assert not re.search(r"\b(?:3600|900)\s*\*\s*\d", code)


def test_generated_protobuf_matches_the_contract(tmp_path):
    subprocess.run([sys.executable, "-m", "grpc_tools.protoc", f"-I{ROOT / 'src'}", f"--python_out={tmp_path}",
                    str(ROOT / "src/sfp/proto/telemetry.proto")], check=True)
    fresh = (tmp_path / "sfp/proto/telemetry_pb2.py").read_text()
    committed = (ROOT / "src/sfp/proto/telemetry_pb2.py").read_text()
    strip = lambda s: "\n".join(x for x in s.splitlines() if "Protobuf Python Version" not in x  # noqa: E731
                                and "ValidateProtobufRuntimeVersion" not in x and not re.match(r"\s+\d+,$", x))
    assert "_serialized_start" in fresh and fresh.split("DESCRIPTOR = ")[1].split("\n")[0] == \
        committed.split("DESCRIPTOR = ")[1].split("\n")[0], "run scripts/gen_proto.sh"
    assert strip(fresh).count("\n") > 10 and strip(committed).count("\n") > 10


def test_heldout_fleet_is_named_only_by_the_evaluation():
    for f in files(["src", "tests"]):
        if f.name == "test_invariants.py":
            continue
        assert "heldout" not in f.read_text(), f


def test_readme_is_generated_from_the_reports():
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    from scripts.readme import render
    assert readme.read_text() == render(), "run python scripts/readme.py"


def test_numbers_quoted_in_the_docs_come_from_the_report():
    import json
    r = json.loads((ROOT / "reports/evaluation.json").read_text())["runs"]
    decisions = (ROOT / "docs/decisions.md").read_text()
    ota = (ROOT / "docs/ota.md").read_text()
    assert f"{r['without_store_and_forward']['exits_lost_in_transit']:,} exit events" in decisions
    assert f"{r['without_ab_updates_and_staged_rollout']['devices_bricked']:,}" in decisions
    d = r["platform"]["disputes"]
    assert f"upheld {d['wrong_fines_upheld']}\nof {d['wrong_fines_upheld'] + d['wrong_fines_cancelled']:,}" in decisions
    assert f"cancelled {d['right_fines_cancelled']} of {d['right_fines_upheld'] + d['right_fines_cancelled']:,}" in decisions
    assert f"ran on {r['platform']['devices_that_ran_the_broken_build']} device" in ota
    assert f"{r['without_staged_rollout']['devices_that_ran_the_broken_build']} without it" in ota
