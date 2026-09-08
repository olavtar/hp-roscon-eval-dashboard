"""Reads a frozen directory of episode/manifest JSON files.

This is the booth/offline mode: no Kafka or MinIO required. Accepts:

- a flat directory of `<episode_id>.json` files
- MinIO's key layout, `<model_version>/<episode_id>.json`
- a JSON *array* of episode records in one file (the documented EVAL_DIR
  contract: `/data/eval/<model_version>.json`)
- the eval-harness `{model_version, eval_config, aggregate, episodes}` shape
  used by docs/eval-records/phase3-ladder/*.json -- each entry in `episodes`
  is exploded into a normal episode record so it flows through the same
  normalize/aggregate path as everything else.

an rglob covers the directory shapes without caring which one it's given.
"""
from __future__ import annotations

import json
import logging
import pathlib
import re
from typing import Iterator

from eval_dashboard import schema

log = logging.getLogger("eval_dashboard.files")

# eval-teacher-v1-s1050.json is a second seed-batch of eval-teacher-v1.json,
# not a distinct policy -- ladder_report.py merges "<name>-s<seed>" files
# into their base under the base's own tag. Stripping the suffix here
# reproduces that so an N=100 rung shows up as one 100-episode version
# instead of two 50-episode ones.
_SEED_EXTENSION = re.compile(r"-s\d+$")


def _strip_seed_extension(model_version: str) -> str:
    return _SEED_EXTENSION.sub("", model_version)


def _iter_eval_harness_episodes(raw: dict) -> Iterator[dict]:
    base_version = _strip_seed_extension(raw.get("model_version", ""))
    eval_config = raw.get("eval_config") or {}
    scene = eval_config.get("scene")
    reset_mode = eval_config.get("reset_mode")
    for ep in raw.get("episodes", []):
        if not isinstance(ep, dict) or "seed" not in ep:
            continue
        yield {
            "episode_id": f"{base_version}-seed{ep['seed']}",
            "model_version": base_version,
            "has_failure": False,
            "task_success": ep.get("task_success"),
            "cubes_placed": ep.get("cubes_placed"),
            "avg_smoothness": ep.get("avg_smoothness"),
            "scene": scene,
            "timestamp": raw.get("timestamp"),
            "curation_verdict": None,
            "rollout": {"steps": ep.get("steps")},
            "eval_seed": ep.get("seed"),
            "eval_scene": scene,
            "eval_reset_mode": reset_mode,
        }


def _iter_raw(raw) -> Iterator[dict]:
    if isinstance(raw, dict) and isinstance(raw.get("aggregate"), dict) and isinstance(raw.get("episodes"), list):
        yield from _iter_eval_harness_episodes(raw)
    elif isinstance(raw, list):
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
                else:
                    self.skipped += 1
            if not yielded and not isinstance(raw, (list, dict)):
                self.skipped += 1
