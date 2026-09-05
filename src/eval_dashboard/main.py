"""Entrypoint: wires configured sources to two independent in-memory panels
and a read-only Flask API/UI.

Two panels, deliberately not conflated:

- "controlled" -- the comparison the ticket is about (fixed-seed eval files
  at EVAL_DIR, or in file mode the directory of episode records when that's
  the only source). Primary evidence for "did the policy measurably improve".
- "operational" -- the live flywheel's curated+rejected population, or a
  *separate* export of those records. Health-of-the-pipeline, not the
  controlled claim. Hidden in the UI when empty.

Neither panel persists anything of its own: both are rebuilt from their
source(s) on every process start, which is what makes a restart safe.
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading
import time
from typing import Iterable

import yaml

from . import aggregate
from .sources.file_source import FileSource
from .sources.kafka_source import KafkaSource
from .sources.minio_source import MinioSource
from .web.app import create_app

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("eval_dashboard")

REJECTED_POLL_SECONDS = 30


class Store:
    """Dedupes by episode_id (last write wins, so a MinIO re-list or a
    Kafka-triggered re-fetch of the same episode is a no-op) and drops
    injected demo failures (`has_failure`) before they ever reach
    aggregate.py -- those are a curation-gate test fixture, not a real
    policy outcome, and would understate success rate if counted."""

    def __init__(self, dataset_sizes: dict[str, int] | None = None, origin: str = ""):
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}
        self._dropped_failure_ids: set[str] = set()
        self._dataset_sizes = dataset_sizes or {}
        self.origin = origin
        self.dropped_has_failure = 0
        self.duplicate_episode_ids = 0
        self.rejected_last_checked: float | None = None

    def merge(self, records: Iterable[dict]) -> None:
        with self._lock:
            for r in records:
                if not r:
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
                existing = self._by_id.get(r["episode_id"])
                if existing is not None and existing.get("curation_verdict") != r.get("curation_verdict"):
                    # Same episode_id with a *different* verdict than before --
                    # e.g. present in both episodes-curated and
                    # episodes-rejected. This is the real warning sign the
                    # brief calls out; it deliberately does NOT fire on the
                    # 30s episodes-rejected re-poll re-merging the same
                    # records with the same verdict every cycle.
                    self.duplicate_episode_ids += 1
                self._by_id[r["episode_id"]] = r

    def replace(self, records: Iterable[dict]) -> None:
        """Rebuild from scratch. File-mode poll uses this so a restart and
        a later rescan of the same directory produce the same counters."""
        materialized = [r for r in records if r]
        with self._lock:
            self._by_id = {}
            self._dropped_failure_ids = set()
            self.dropped_has_failure = 0
            self.duplicate_episode_ids = 0
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
                "dataset_size": self._dataset_sizes.get(v),
            }
        return {
            "origin": origin,
            "episode_count": len(records),
            "dropped_has_failure": dropped,
            "duplicate_episode_ids": duplicates,
            "rejected_last_checked": rejected_last_checked,
            "smoothness_bin_edges": aggregate.SMOOTHNESS_BINS,
            "versions": versions,
        }


def load_dataset_sizes(path: str) -> dict[str, int]:
    p = pathlib.Path(path)
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def file_panel_dirs(records_dir: str, eval_dir: str) -> dict[str, str | None]:
    """Where file-mode directories should land so the same tree is never
    shown as both the controlled claim and the operational health signal.

    - EVAL_DIR present, RECORDS_DIR a different tree → controlled / operational
    - only one of the two exists → that tree is the comparison (controlled)
    - both resolve to the same path → controlled only
    """
    rec = pathlib.Path(records_dir)
    ev = pathlib.Path(eval_dir)
    rec_ok, ev_ok = rec.exists(), ev.exists()
    same = rec_ok and ev_ok and rec.resolve() == ev.resolve()
    if same:
        return {"controlled": str(rec.resolve()), "operational": None}
    if ev_ok and rec_ok:
        return {"controlled": str(ev.resolve()), "operational": str(rec.resolve())}
    if ev_ok:
        return {"controlled": str(ev.resolve()), "operational": None}
    if rec_ok:
        return {"controlled": str(rec.resolve()), "operational": None}
    return {"controlled": None, "operational": None}


def watch_files(store: Store, directory: str) -> None:
    interval = float(os.environ.get("FILE_POLL_SECONDS", "5"))
    if interval <= 0:
        return

    def loop() -> None:
        while True:
            time.sleep(interval)
            try:
                store.replace(FileSource(directory).read())
            except Exception:
                log.exception("file poll failed for %s", directory)

    threading.Thread(target=loop, daemon=True, name=f"watch:{directory}").start()


def run_live(operational: Store) -> None:
    minio = MinioSource(
        endpoint=os.environ["S3_ENDPOINT"],
        access_key=os.environ["S3_ACCESS_KEY"],
        secret_key=os.environ["S3_SECRET_KEY"],
    )
    curated_bucket = os.environ.get("S3_CURATED_BUCKET", "episodes-curated")
    rejected_bucket = os.environ.get("S3_REJECTED_BUCKET", "episodes-rejected")

    log.info("seeding operational panel from %s + %s", curated_bucket, rejected_bucket)
    operational.merge(minio.list_bucket(curated_bucket))
    operational.merge(minio.list_bucket(rejected_bucket))
    operational.rejected_last_checked = time.time()
    operational.origin = "live:kafka+minio"

    def poll_rejected() -> None:
        # Rejected episodes never get a Kafka notification (only sync-agent
        # publishes, and only for curation passes), so this is the only way
        # the operational panel ever sees them after startup. The mirror job
        # that populates episodes-rejected runs every 5 minutes upstream, so
        # a 30s poll here is frequent enough not to be the bottleneck -- the
        # UI surfaces `rejected_last_checked` so a stale success rate is
        # visible rather than silently trusted.
        while True:
            time.sleep(REJECTED_POLL_SECONDS)
            try:
                operational.merge(minio.list_bucket(rejected_bucket))
                operational.rejected_last_checked = time.time()
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
                operational.merge([record])

    threading.Thread(target=consume_kafka, daemon=True).start()


def main() -> None:
    dataset_sizes = load_dataset_sizes(os.environ.get("VERSIONS_FILE", "config/versions.yaml"))
    operational = Store(dataset_sizes)
    controlled = Store(dataset_sizes)

    source_mode = os.environ.get("SOURCE_MODE", "files")
    records_dir = os.environ.get("RECORDS_DIR", "/records")
    eval_dir = os.environ.get("EVAL_DIR", "/data/eval")

    if source_mode == "live":
        run_live(operational)
        if pathlib.Path(eval_dir).exists():
            controlled.origin = f"files:{pathlib.Path(eval_dir).resolve()}"
            controlled.replace(FileSource(eval_dir).read())
            watch_files(controlled, eval_dir)
        else:
            log.info("no EVAL_DIR at %s -- controlled panel will be empty", eval_dir)
    elif source_mode == "files":
        dirs = file_panel_dirs(records_dir, eval_dir)
        if dirs["controlled"]:
            controlled.origin = f"files:{dirs['controlled']}"
            controlled.replace(FileSource(dirs["controlled"]).read())
            watch_files(controlled, dirs["controlled"])
        else:
            log.info("no episode files at RECORDS_DIR=%s or EVAL_DIR=%s", records_dir, eval_dir)
        if dirs["operational"]:
            operational.origin = f"files:{dirs['operational']}"
            operational.replace(FileSource(dirs["operational"]).read())
            watch_files(operational, dirs["operational"])
    else:
        raise ValueError(f"Unknown SOURCE_MODE={source_mode!r}, expected live|files")

    app = create_app(operational, controlled, source_mode)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
