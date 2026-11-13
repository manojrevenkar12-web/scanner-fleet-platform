"""Over-the-air updates with two slots (A/B), signed bundles and automatic rollback.

A bundle is a manifest, an Ed25519 signature over the manifest, and the payload. The device refuses a
bundle whose signature, payload hash, device type, architecture or version does not check out. It
installs into the slot it is not running, and the bootloader tries the new slot a limited number of
times. The platform commits the new slot only after it has been healthy for a while; if it never
reports healthy, the bootloader falls back to the old slot by itself.

On hardware this state lives in the bootloader environment (U-Boot or GRUB, as RAUC and Mender use);
here it is a JSON file replaced atomically, behind the same small interface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .config import atomic_write


class Rejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Manifest:
    version: str
    device_types: tuple[str, ...]
    arch: str
    sha256: str
    size: int
    min_version: str = "0.0.0"

    def encode(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class Bundle:
    manifest: bytes
    signature: bytes
    payload: bytes


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def build(key: Ed25519PrivateKey, version: str, device_types, arch: str, payload: bytes,
          min_version: str = "0.0.0") -> Bundle:
    m = Manifest(version, tuple(device_types), arch, hashlib.sha256(payload).hexdigest(), len(payload), min_version)
    raw = m.encode()
    return Bundle(raw, key.sign(raw), payload)


@dataclass
class SlotState:
    active: str = "a"                       # the committed slot
    versions: dict = field(default_factory=lambda: {"a": "0.0.0", "b": ""})
    trying: str | None = None               # slot installed and being tried
    attempts_left: int = 0
    booted: str = "a"                       # the slot running right now
    last_result: str = "none"


class FileSlots:
    """Slot payloads and the boot state as files; on a device the payload goes to a partition."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self) -> SlotState:
        p = self.root / "state.json"
        return SlotState(**json.loads(p.read_text())) if p.exists() else SlotState()

    def save(self, s: SlotState) -> None:
        atomic_write(self.root / "state.json", json.dumps(asdict(s), sort_keys=True).encode())

    def write(self, slot: str, payload: bytes) -> None:
        atomic_write(self.root / f"slot-{slot}.img", payload)


class MemorySlots:
    def __init__(self, version: str = "0.0.0"):
        self.state = SlotState(versions={"a": version, "b": ""})
        self.payloads: dict[str, bytes] = {}

    def load(self) -> SlotState:
        return self.state

    def save(self, s: SlotState) -> None:
        self.state = s

    def write(self, slot: str, payload: bytes) -> None:
        self.payloads[slot] = payload


class Updater:
    def __init__(self, slots, device_type: str, arch: str, trusted: list[Ed25519PublicKey], boot_attempts: int,
                 verify: bool = True, ab: bool = True):
        self.slots, self.device_type, self.arch = slots, device_type, arch
        self.trusted, self.boot_attempts = trusted, boot_attempts
        self.verify_on, self.ab = verify, ab

    @property
    def state(self) -> SlotState:
        return self.slots.load()

    def running_version(self) -> str:
        s = self.state
        return s.versions[s.booted]

    def verify(self, b: Bundle) -> Manifest:
        if self.verify_on:
            for k in self.trusted:
                try:
                    k.verify(b.signature, b.manifest)
                    break
                except InvalidSignature:
                    continue
            else:
                raise Rejected("signature")
        m = Manifest(**{**json.loads(b.manifest), "device_types": tuple(json.loads(b.manifest)["device_types"])})
        if self.verify_on:
            if hashlib.sha256(b.payload).hexdigest() != m.sha256 or len(b.payload) != m.size:
                raise Rejected("payload_hash")
            if self.device_type not in m.device_types or m.arch != self.arch:
                raise Rejected("incompatible")
            if vtuple(self.running_version()) < vtuple(m.min_version):
                raise Rejected("needs_newer_base")
            if vtuple(m.version) <= vtuple(self.running_version()):
                raise Rejected("not_newer")
        return m

    def install(self, b: Bundle) -> str:
        """Verify and write to the other slot. Returns the version to reboot into."""
        m = self.verify(b)
        s = self.state
        target = ({"a": "b", "b": "a"}[s.active]) if self.ab else s.active
        self.slots.write(target, b.payload)
        s.versions[target] = m.version
        if self.ab:
            s.trying, s.attempts_left = target, self.boot_attempts
        s.last_result = "installed"
        self.slots.save(s)
        return m.version

    def boot(self) -> str:
        """What the bootloader does at power-on. Returns the slot booted."""
        s = self.state
        if s.trying and s.attempts_left > 0:
            s.attempts_left -= 1
            s.booted = s.trying
        elif s.trying:
            s.trying, s.booted, s.last_result = None, s.active, "rolled_back"
        else:
            s.booted = s.active
        self.slots.save(s)
        return s.booted

    def commit(self) -> bool:
        """Called by the platform once the new slot has been healthy long enough."""
        s = self.state
        if not s.trying or s.booted != s.trying:
            return False
        s.active, s.trying, s.attempts_left, s.last_result = s.booted, None, 0, "committed"
        self.slots.save(s)
        return True

    def revert(self) -> bool:
        """Fleet-ordered rollback to the other slot's version, if it still holds one."""
        s = self.state
        other = {"a": "b", "b": "a"}[s.active]
        if not self.ab or not s.versions.get(other):
            return False
        s.active, s.booted, s.trying, s.last_result = other, other, None, "reverted"
        self.slots.save(s)
        return True
