#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A cache for upstream answers, keyed on the request itself.

Why this is safe rather than a shortcut: the endpoint is very nearly a function.
Re-sending a byte-identical question about 255 thinkers gave r = 0.997, a mean
difference of 0.0061, zero people moving more than 0.05, and the same 172 of 255
landing on the "yes" side. That measurement is in docs/design.md under
「为什么每个人问两遍」. So a hit here does not approximate an answer -- it
replays one that already happened.

The key is (url, request body). `upstreams._post` serialises the payload once
with `json.dumps`, so the same dict is the same bytes, and the model name is
already inside the key. Two consequences worth stating out loud: changing the
model misses the cache, and changing the API key does not -- the same question
to the same model is the same answer whichever key paid for it.

Three rules it does not break:

  * **Failures are never stored.** Only a response carrying `answers` (Jev) or
    `choices` (DeepSeek) is written. Caching a timeout would turn one bad minute
    on the network into a permanent answer.
  * **A hit is priced at zero.** `upstreams._post` moves the original figures
    into `saved_input_tokens` / `saved_output_tokens` and zeroes the live ones,
    so a caller that sums `usage` reports what this run actually spent rather
    than a bill it did not pay.
  * **The cache never raises into a run.** Missing file, corrupt row, locked
    database -- all of them degrade to a miss. A run is expensive and a cache is
    an optimisation; the optimisation does not get to fail the run.

Stored in its own file, for the same reason the keys are: this is tens of megabytes of
re-servable JSON, and it belongs next to the keys -- outside anything a backup or a
`git add .` would sweep up with the source.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "should_i.jevcache.db")

# The switch. Unset means on: a cache that has to be remembered is a cache that
# gets left off. Set it to 0/off to force a run to spend real tokens, which is
# what you want when measuring what a run costs.
ENV_NAME = "SHOULD_I_JEV_CACHE"
OFF_VALUES = ("", "0", "off", "no", "false", "none")

# Evict least-recently-used past this. A full 11-chunk sweep is about 11 x 200 KB
# of answers, so this holds roughly fifty of them, which is more than the number
# of distinct questions anyone asks in a session.
MAX_BYTES = 64 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS response (
    digest   TEXT PRIMARY KEY,
    url      TEXT NOT NULL,
    body     TEXT NOT NULL,
    nbytes   INTEGER NOT NULL,
    made_at  REAL NOT NULL,
    used_at  REAL NOT NULL,
    hits     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS response_used_at ON response (used_at);
"""

_LOCK = threading.Lock()


def path():
    override = os.environ.get(ENV_NAME)
    return DEFAULT_DB if override is None else override


def enabled():
    override = os.environ.get(ENV_NAME)
    if override is None:
        return True
    return override.strip().lower() not in OFF_VALUES


def digest(url, body):
    """The key. `body` is the exact bytes that would go on the wire."""
    hasher = hashlib.sha256()
    hasher.update(url.encode("utf-8"))
    # A URL cannot contain a newline, so this separator cannot be forged by a
    # URL that happens to end in whatever a body starts with.
    hasher.update(b"\n")
    hasher.update(body if isinstance(body, bytes) else str(body).encode("utf-8"))
    return hasher.hexdigest()


def _connect():
    conn = sqlite3.connect(path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def get(key):
    """The stored response for this key, or None. Never raises."""
    if not enabled():
        return None
    try:
        with _LOCK, _connect() as conn:
            row = conn.execute(
                "SELECT body FROM response WHERE digest = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            # Mark it used before parsing: a row that turns out to be corrupt is
            # about to be deleted, and this way a parse failure cannot leave the
            # row young enough to survive the next trim.
            conn.execute(
                "UPDATE response SET used_at = ?, hits = hits + 1 WHERE digest = ?",
                (time.time(), key),
            )
            data = json.loads(row[0])
    except Exception:  # noqa: BLE001 - a cache miss is the only failure mode
        return None
    return data if isinstance(data, dict) else None


def put(key, url, response):
    """Remember one successful response. Never raises."""
    if not enabled() or not storable(response):
        return
    try:
        text = json.dumps(response, ensure_ascii=False)
        now = time.time()
        with _LOCK, _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO response"
                " (digest, url, body, nbytes, made_at, used_at, hits)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)",
                (key, url, text, len(text.encode("utf-8")), now, now),
            )
            _trim(conn)
    except Exception:  # noqa: BLE001
        return


def storable(response):
    """Is this an answer, or the absence of one?

    Checked against the two success shapes rather than against the error shapes:
    a new way of failing should default to "do not store", and only these two
    keys mean an upstream actually said something.
    """
    if not isinstance(response, dict):
        return False
    return bool(response.get("answers") or response.get("choices"))


def _trim(conn):
    """Drop least-recently-used rows until the file fits MAX_BYTES."""
    total = conn.execute("SELECT COALESCE(SUM(nbytes), 0) FROM response").fetchone()[0]
    if total <= MAX_BYTES:
        return
    freed = 0
    for key, size in conn.execute(
        "SELECT digest, nbytes FROM response ORDER BY used_at ASC"
    ).fetchall():
        conn.execute("DELETE FROM response WHERE digest = ?", (key,))
        freed += size
        if total - freed <= MAX_BYTES:
            break


def forget():
    """Empty the cache. For tests and for when a key changes hands."""
    if not enabled():
        return
    try:
        with _LOCK, _connect() as conn:
            conn.execute("DELETE FROM response")
    except Exception:  # noqa: BLE001
        return
