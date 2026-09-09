"""Entrypoint: wires a configured source to one in-memory population and a
read-only Flask API/UI.

One view, per `model_version`, fed by whichever source is active:

- SOURCE_MODE=files -- a directory of episode JSON records (RECORDS_DIR).
- SOURCE_MODE=live -- Kafka+MinIO curated episodes, merged with the MinIO
  rejected bucket (Kafka never notifies for rejects).

Persists nothing of its own: rebuilt from source on every process start, so
a restart or a fresh file-directory replay reproduces the same numbers.
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading
import time
from typing import Iterable

import yaml

from . import aggregate, schema
from .sources.file_source import FileSource
from .sources.kafka_source import KafkaSource
from .sources.minio_source import MinioSource
from .web.app import create_app

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("eval_dashboard")

REJECTED_POLL_SECONDS = 30


class Store:
    """Dedupes by episode_id. An identical re-list is a no-op; two records
    with the same episode_id but different scored fields are quarantined and
    excluded from aggregates. Injected demo failures (`has_failure`) are
    dropped before aggregate.py sees them."""

    def __init__(self, version_meta: dict[str, dict] | None = None, origin: str = ""):
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}
        self._dropped_failure_ids: set[str] = set()
        self._quarantined: set[str] = set()
        self._version_meta = version_meta or {}
        self.origin = origin
        self.dropped_has_failure = 0
        self.dropped_invalid = 0
        self.duplicate_episode_ids = 0
        self.conflicting_episode_ids = 0
        self.rejected_last_checked: float | None = None

    def merge(self, records: Iterable[dict]) -> None:
        with self._lock:
            for r in records:
                if not r:
                    self.dropped_invalid += 1
                    continue
                if schema.validate_normalized(r):
                    self.dropped_invalid += 1
                    continue
                if r.get("has_failure"):
                    eid = r["episode_id"]
                    # Idempotent: the 30s rejected-bucket poll re-feeds the
                    # same objects; counting each pass would inflate the
                    # integrity panel.
                    if eid not in self._dropped_failure_ids:
                        self._dropped_failure_ids.add(eid)
                        self.dropped_has_failure += 1
                    continue
                eid = r["episode_id"]
                if eid in self._quarantined:
                    continue
                existing = self._by_id.get(eid)
                if existing is not None:
                    if not schema.records_conflict(existing, r):
                        continue
                    self._quarantined.add(eid)
                    del self._by_id[eid]
                    self.conflicting_episode_ids += 1
                    if existing.get("curation_verdict") != r.get("curation_verdict"):
                        self.duplicate_episode_ids += 1
                    continue
                self._by_id[eid] = r

    def replace(self, records: Iterable[dict]) -> None:
        """Rebuild from scratch. File-mode poll uses this so a restart and
        a later rescan of the same directory produce the same counters."""
        materialized = [r for r in records if r]
        with self._lock:
            self._by_id = {}
            self._dropped_failure_ids = set()
            self._quarantined = set()
            self.dropped_has_failure = 0
            self.dropped_invalid = 0
            self.duplicate_episode_ids = 0
            self.conflicting_episode_ids = 0
        self.merge(materialized)

    def episodes(self, model_version: str | None = None) -> list[dict]:
        with self._lock:
            records = list(self._by_id.values())
        if model_version:
            records = [r for r in records if r["model_version"] == model_version]
        return records

    def snapshot(self) -> dict:
        with self._lock:
            records = list(self._by_id.values())
            dropped = self.dropped_has_failure
            duplicates = self.duplicate_episode_ids
            rejected_last_checked = self.rejected_last_checked
            origin = self.origin
        stats = aggregate.aggregate(records)
        versions = {}
        for v, s in stats.items():
            ci_low, ci_high = s.success_ci
            meta = self._version_meta.get(v) or {}
            versions[v] = {
                "episode_count": s.episode_count,
                "success_count": s.success_count,
                "success_rate": s.success_rate,
                "success_rate_incomplete": s.success_rate_incomplete,
                "success_ci": [ci_low, ci_high],
                "avg_cubes_placed": s.avg_cubes_placed,
                "mean_smoothness": s.mean_smoothness,
                "smoothness_n": s.smoothness_n,
                "cubes_placed": s.cubes_placed,
                "smoothness_hist": s.smoothness_hist,
                "cube_bins_reconcile": s.cube_bins_reconcile,
                "success_matches_full_cubes": s.success_matches_full_cubes,
                "dataset_size": meta.get("size"),
                "parent": meta.get("parent"),
            }
        return {
            "origin": origin,
            "episode_count": len(records),
            "dropped_has_failure": dropped,
            "dropped_invalid": self.dropped_invalid,
            "duplicate_episode_ids": duplicates,
            "conflicting_episode_ids": self.conflicting_episode_ids,
            "rejected_last_checked": rejected_last_checked,
            "smoothness_bin_edges": aggregate.SMOOTHNESS_BINS,
            "versions": versions,
        }


def load_version_meta(path: str) -> dict[str, dict]:
    """Each entry is either a plain int (`version: 20`, no known parent -- a
    baseline or a version whose lineage isn't documented) or a dict
    (`version: {size: 20, parent: eval-teacher-v1}`) when the fine-tune
    parent is known. Both shapes coexist in the same file."""
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text()) or {}
    meta: dict[str, dict] = {}
    for version, entry in raw.items():
        if isinstance(entry, dict):
            meta[version] = {"size": entry.get("size"), "parent": entry.get("parent")}
        else:
            meta[version] = {"size": entry, "parent": None}
    return meta


def watch_files(store: Store, directory: str, transform=lambda records: records) -> None:
    interval = float(os.environ.get("FILE_POLL_SECONDS", "5"))
    if interval <= 0:
        return

    def loop() -> None:
        while True:
            time.sleep(interval)
            try:
                store.replace(transform(FileSource(directory).read()))
            except Exception:
                log.exception("file poll failed for %s", directory)

    threading.Thread(target=loop, daemon=True, name=f"watch:{directory}").start()


def run_live(store: Store) -> None:
    """`schema.apply_lineage_rules` is applied to every path here (initial
    listing, the rejected-bucket poll, and each Kafka-triggered fetch) --
    the client-side guard against eval-* contamination sitting in Kafka's
    append-only history, and the pre-teacher lineage grouping."""
    minio = MinioSource(
        endpoint=os.environ["S3_ENDPOINT"],
        access_key=os.environ["S3_ACCESS_KEY"],
        secret_key=os.environ["S3_SECRET_KEY"],
    )
    curated_bucket = os.environ.get("S3_CURATED_BUCKET", "episodes-curated")
    rejected_bucket = os.environ.get("S3_REJECTED_BUCKET", "episodes-rejected")

    log.info("seeding from %s + %s", curated_bucket, rejected_bucket)
    store.merge(schema.apply_lineage_rules(minio.list_bucket(curated_bucket)))
    store.merge(schema.apply_lineage_rules(minio.list_bucket(rejected_bucket)))
    store.rejected_last_checked = time.time()

    def poll_rejected() -> None:
        # Rejected episodes never get a Kafka notification (only sync-agent
        # publishes, and only for curation passes), so this is the only way
        # the store ever sees them after startup. The mirror job that
        # populates episodes-rejected runs every 5 minutes upstream, so a
        # 30s poll here is frequent enough not to be the bottleneck -- the
        # UI surfaces `rejected_last_checked` so a stale success rate is
        # visible rather than silently trusted.
        while True:
            time.sleep(REJECTED_POLL_SECONDS)
            try:
                store.merge(schema.apply_lineage_rules(minio.list_bucket(rejected_bucket)))
                store.rejected_last_checked = time.time()
            except Exception:
                log.exception("episodes-rejected poll failed")

    threading.Thread(target=poll_rejected, daemon=True).start()

    def consume_kafka() -> None:
        kafka = KafkaSource(
            bootstrap_servers=os.environ["KAFKA_BOOTSTRAP"],
            topic=os.environ.get("KAFKA_TOPIC", "episode-manifests"),
        )
        for notification in kafka.read():
            s3_uri = notification.get("s3_uri")
            if not s3_uri:
                continue
            try:
                record = minio.get_by_uri(s3_uri)
            except Exception:
                log.exception("failed to resolve %s from MinIO", s3_uri)
                continue
            if record:
                store.merge(schema.apply_lineage_rules([record]))

    threading.Thread(target=consume_kafka, daemon=True).start()


def main() -> None:
    version_meta = load_version_meta(os.environ.get("VERSIONS_FILE", "config/versions.yaml"))
    store = Store(version_meta)

    source_mode = os.environ.get("SOURCE_MODE", "files")
    records_dir = os.environ.get("RECORDS_DIR", "/records")

    if source_mode == "live":
        store.origin = "live:kafka+minio"
        run_live(store)
    elif source_mode == "files":
        if pathlib.Path(records_dir).exists():
            store.origin = f"files:{pathlib.Path(records_dir).resolve()}"
            store.replace(schema.apply_lineage_rules(FileSource(records_dir).read()))
            watch_files(store, records_dir, transform=schema.apply_lineage_rules)
        else:
            log.info("no episode files at RECORDS_DIR=%s", records_dir)
    else:
        raise ValueError(f"Unknown SOURCE_MODE={source_mode!r}, expected live|files")

    app = create_app(store, source_mode)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
