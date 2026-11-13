"""Reads config/*.toml. Every tunable number in the platform comes through here."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@cache
def load(name: str) -> dict:
    with open(ROOT / "config" / f"{name}.toml", "rb") as f:
        return tomllib.load(f)


def platform() -> dict:
    return load("platform")


def device_type(name: str) -> dict:
    types = load("devices")["types"]
    if name not in types:
        raise KeyError(f"unknown device type {name!r}; known: {sorted(types)}")
    return types[name]
