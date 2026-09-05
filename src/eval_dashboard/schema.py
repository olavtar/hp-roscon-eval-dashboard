"""Normalizes episode/manifest records from any source into one shape.

Every EpisodeSource funnels its raw JSON through `normalize()` before
handing records to the store/aggregate.py. That's what guarantees the file,
Kafka+MinIO, and MinIO-listing paths produce identical numbers for
identical underlying data -- there is exactly one place that knows what a
record looks like.

Tolerant of the upcoming `dataset_path` field (ignored, per the brief) and
of the Kafka manifest's reduced field set (sync-agent publishes a subset of
the full episode JSON -- see hp-roscon-flywheel's sync_agent.py). Missing
optional fields become None; aggregate.py decides how to treat that.
"""
from __future__ import annotations

REQUIRED = ("episode_id", "model_version")


def as_bool(value, default: bool = False) -> bool:
    """JSON booleans, 0/1, and the strings some exporters emit."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def normalize(record: dict) -> dict | None:
    if not isinstance(record, dict) or not all(record.get(k) for k in REQUIRED):
        return None
    return {
        "episode_id": record["episode_id"],
        "model_version": record["model_version"],
        "has_failure": as_bool(record.get("has_failure"), False),
        "task_success": as_bool(record.get("task_success"), False),
        "cubes_placed": record.get("cubes_placed"),
        "avg_smoothness": record.get("avg_smoothness"),
        "scene": record.get("scene"),
        "timestamp": record.get("timestamp"),
        "curation_verdict": record.get("curation_verdict"),
        "rollout_steps": (record.get("rollout") or {}).get("steps"),
    }
