"""Store-and-forward: telemetry waits on the device while the uplink is down and is removed only when
the broker confirms it (MQTT PUBACK).

The outbox is bounded. When it is full, an incoming message evicts the oldest message of a lower
priority (health snapshots before parking events), so a long outage costs fine-grained health history
and never billing data. Every drop is counted.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

EVENTS, OTA, HEALTH, LOG = 3, 3, 1, 0     # priorities: higher survives longer


@dataclass
class Stats:
    accepted: int = 0
    evicted: int = 0
    refused: int = 0
    sent: int = 0


class MemoryStore:
    def __init__(self):
        self.rows: dict[int, tuple[int, bytes]] = {}

    def add(self, seq, prio, body):
        self.rows[seq] = (prio, body)

    def remove(self, seqs):
        for s in seqs:
            self.rows.pop(s, None)

    def oldest_below(self, prio):
        best = None
        for s, (p, _) in self.rows.items():
            if p < prio and (best is None or (p, s) < best):
                best = (p, s)
        return None if best is None else best[1]

    def batch(self, n):
        return [(s, self.rows[s][1]) for s in sorted(self.rows)[:n]]

    def __len__(self):
        return len(self.rows)

    def max_seq(self):
        return max(self.rows, default=0)


class SqliteStore:
    """On a real device: survives a reboot. WAL with synchronous=NORMAL keeps flash writes low."""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("pragma journal_mode=wal")
        self.db.execute("pragma synchronous=normal")
        self.db.execute("create table if not exists outbox (seq integer primary key, prio int, body blob)")

    def add(self, seq, prio, body):
        self.db.execute("insert into outbox values (?,?,?)", (seq, prio, body))

    def remove(self, seqs):
        self.db.executemany("delete from outbox where seq = ?", [(s,) for s in seqs])

    def oldest_below(self, prio):
        r = self.db.execute("select seq from outbox where prio < ? order by prio, seq limit 1", (prio,)).fetchone()
        return r and r[0]

    def batch(self, n):
        return self.db.execute("select seq, body from outbox order by seq limit ?", (n,)).fetchall()

    def __len__(self):
        return self.db.execute("select count(*) from outbox").fetchone()[0]

    def max_seq(self):
        return self.db.execute("select coalesce(max(seq), 0) from outbox").fetchone()[0]


class Outbox:
    def __init__(self, capacity: int, store=None, next_seq: int | None = None):
        self.capacity = capacity
        self.store = store if store is not None else MemoryStore()
        self.seq = next_seq if next_seq is not None else self.store.max_seq()
        self.stats = Stats()

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def put(self, seq: int, prio: int, body: bytes) -> bool:
        if len(self.store) >= self.capacity:
            victim = self.store.oldest_below(prio)
            if victim is None:
                self.stats.refused += 1
                return False
            self.store.remove([victim])
            self.stats.evicted += 1
        self.store.add(seq, prio, body)
        self.stats.accepted += 1
        return True

    def batch(self, n: int) -> list[tuple[int, bytes]]:
        return self.store.batch(n)

    def ack(self, seqs: list[int]) -> None:
        self.store.remove(seqs)
        self.stats.sent += len(seqs)

    def __len__(self) -> int:
        return len(self.store)
