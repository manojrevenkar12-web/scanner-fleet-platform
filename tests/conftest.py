import copy

import pytest

from sfp.fleet.world import generate, load
from sfp.platform import settings

ROOT = settings.ROOT


@pytest.fixture(scope="session")
def fleet_cfg():
    return load(ROOT / "config/fleet.toml")


@pytest.fixture(scope="session")
def rollout_cfg():
    return load(ROOT / "config/rollout.toml")


@pytest.fixture(scope="session")
def guarantees():
    return dict(settings.platform()["guarantees"])


def small_world(cfg: dict, sites: int = 30, days: int = 5, **over):
    c = copy.deepcopy(cfg)
    c.update(sites=sites, days=days, **over)
    return generate(c)
