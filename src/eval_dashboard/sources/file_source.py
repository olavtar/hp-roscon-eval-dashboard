"""Reads a frozen directory of episode/manifest JSON files.

This is the booth/offline mode: no Kafka or MinIO required, and per the
brief it's meant to be a first-class source, not a fallback. Accepts:

- a flat directory of `<episode_id>.json` files
- MinIO's key layout, `<model_version>/<episode_id>.json`
- a JSON *array* of episode records in one file (the documented EVAL_DIR
  contract: `/data/eval/<model_version>.json`)

an rglob covers the directory shapes without caring which one it's given.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Iterator

from eval_dashboard import schema

log = logging.getLogger("eval_dashboard.files")


def _iter_raw(raw) -> Iterator[dict]:
    if isinstance(raw, list):
        yield from (item for item in raw if isinstance(item, dict))
    elif isinstance(raw, dict):
        if raw.get("episode_id"):
            yield raw
        elif isinstance(raw.get("episodes"), list):
            yield from (item for item in raw["episodes"] if isinstance(item, dict))


class FileSource:
    def __init__(self, directory: str):
        self.directory = pathlib.Path(directory)
        self.skipped = 0

    def read(self) -> Iterator[dict]:
        self.skipped = 0
        if not self.directory.exists():
            return
        for path in sorted(self.directory.rglob("*.json")):
            try:
                raw = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                self.skipped += 1
                log.warning("skipping unreadable %s: %s", path, exc)
                continue
            yielded = False
            for item in _iter_raw(raw):
                normalized = schema.normalize(item)
                if normalized:
                    yielded = True
                    yield normalized
            if not yielded:
                self.skipped += 1
