"""Hardware abstraction: what the platform needs from each kind of hardware, whatever the board.

A device type lists its hardware in config/devices.toml; a backend ("linux" on a real device, "sim" in
tests and the fleet simulation) supplies the implementation. Applications only ever see these
interfaces, so a new modem or accelerator is a new implementation, not a change to the applications.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..platform.health import Check


@runtime_checkable
class Modem(Protocol):
    def signal_dbm(self) -> int | None: ...
    def connected(self) -> bool: ...
    def check(self) -> Check: ...


@runtime_checkable
class Watchdog(Protocol):
    def kick(self) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class Camera(Protocol):
    def fps(self) -> float: ...
    def check(self) -> Check: ...


@runtime_checkable
class Accelerator(Protocol):
    def available(self) -> bool: ...
    def check(self) -> Check: ...


KINDS = {"modem": Modem, "watchdog": Watchdog, "camera": Camera, "accelerator": Accelerator}
REGISTRY: dict[tuple[str, str], type] = {}


def implements(kind: str, backend: str):
    def deco(cls):
        REGISTRY[(kind, backend)] = cls
        return cls
    return deco


class Hardware:
    """The hardware of one device, built from its type's list."""

    def __init__(self, kinds: list[str], backend: str, **options):
        unknown = set(kinds) - set(KINDS)
        if unknown:
            raise KeyError(f"unknown hardware kinds {sorted(unknown)}")
        self.parts = {}
        for k in kinds:
            cls = REGISTRY.get((k, backend))
            if cls is None:
                raise KeyError(f"no {backend} implementation for {k}")
            part = cls(**options.get(k, {}))
            if not isinstance(part, KINDS[k]):
                raise TypeError(f"{cls.__name__} does not implement {k}")
            self.parts[k] = part

    def __getattr__(self, kind: str):
        try:
            return self.__dict__["parts"][kind]
        except KeyError:
            raise AttributeError(kind) from None

    def has(self, kind: str) -> bool:
        return kind in self.parts

    def checks(self) -> dict:
        return {k: p.check for k, p in self.parts.items() if hasattr(p, "check")}
