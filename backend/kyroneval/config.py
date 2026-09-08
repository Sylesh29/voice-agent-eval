"""
Credential loading.

Keys live in a gitignored `.env`, never in tracked source. The assignment is explicit
about this ("Do not commit API keys or credentials") and it is also just correct: the
cassette in `evaluators/judge.py` means a reviewer never needs a credential at all, so
there is no scenario where a committed key buys anything.

Real environment variables always win over `.env`, so CI and one-off overrides behave
the way people expect.

No python-dotenv dependency -- this is twenty lines and the install list stays short.
"""
from __future__ import annotations

import os
from pathlib import Path

# backend/.env first (next to where you run things), then repo root.
SEARCH = [
    Path(__file__).resolve().parents[1] / ".env",
    Path(__file__).resolve().parents[2] / ".env",
]

_loaded = False


def load_env(force: bool = False) -> list[Path]:
    """Populate os.environ from any .env found. Idempotent. Returns files read."""
    global _loaded
    if _loaded and not force:
        return []
    _loaded = True
    read: list[Path] = []
    for path in SEARCH:
        if not path.is_file():
            continue
        read.append(path)
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            # A real env var beats the file. Never clobber an explicit export.
            if key and key not in os.environ:
                os.environ[key] = val
    return read
