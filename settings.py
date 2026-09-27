#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where the API keys come from when they are not in the environment.

Precedence is: this file, then the environment. The file wins because typing a
key into the settings screen is a deliberate act with a visible result right
next to it, and having it silently lose to a stale `export` in some forgotten
shell is the kind of thing that costs an hour of debugging.

Deliberately a file of its own rather than a field somewhere else. There is no
database in this repo to put it in, and a secret that lives in exactly one place
with a 0600 mode is easier to reason about than one that travels with a copy.
This file holds nothing but the two keys.

Nothing here ever hands a key back to the browser. `mask()` is for the one place
a key is mentioned in an HTTP response, and it shows four characters and four
more, which is enough to tell two keys apart and not enough to use one.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "should_i.settings.json")

# The only keys this file will ever hold. A settings file that accepts arbitrary
# names invites a typo that silently does nothing.
FIELDS = ("jev_api_key", "deepseek_api_key")

MAX_KEY_LENGTH = 512


def path():
    return os.environ.get("SHOULD_I_SETTINGS") or DEFAULT_PATH


def load():
    """The saved keys, or {} -- never raises. A corrupt file is a missing file."""
    try:
        with open(path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    found = {}
    for name in FIELDS:
        value = data.get(name)
        # Strings only. This file is written by us, so a number or a list in it
        # means it was hand-edited or corrupted -- and coercing 123 into "123"
        # would turn that into a 401 much later, wearing a normal error's clothes.
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value:
            found[name] = value
    return found


def save(patch):
    """Merge a patch in. An empty string clears that field. Returns the new state.

    Written through a temp file so a crash mid-write cannot leave a half-file
    that reads as "no keys configured" on the next boot.
    """
    data = load()
    for name in FIELDS:
        if name not in patch:
            continue
        value = str(patch.get(name) or "").strip()
        if value:
            data[name] = value
        else:
            data.pop(name, None)
    target = path()
    if data:
        temp = target + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
        os.chmod(temp, 0o600)
        os.replace(temp, target)
    elif os.path.exists(target):
        os.remove(target)
    return data


def get(name):
    return load().get(name) or None


def mask(value):
    """Four and four. Enough to tell two keys apart, not enough to use one."""
    if not value:
        return None
    if len(value) <= 10:
        return "…"
    return "%s…%s" % (value[:4], value[-4:])
