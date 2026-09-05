"""Consumes `episode-manifests` change-notifications: {episode_id, s3_uri, ...}.

This is a notification stream, not the source of truth -- MinIO is. On
every message, the caller (main.py) resolves `s3_uri` back to the full
record via MinioSource.get_by_uri() and normalizes from there. Kafka tells
you something arrived; MinIO tells you what it is.

Uses a fresh, never-committed consumer group each run + auto_offset_reset=
earliest, so a restart always replays the full topic from the beginning --
there is no offset state to get out of sync.
"""
from __future__ import annotations

import json
import uuid
from typing import Iterator

from kafka import KafkaConsumer


class KafkaSource:
    def __init__(self, bootstrap_servers: str, topic: str = "episode-manifests"):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic

    def read(self) -> Iterator[dict]:
        """Blocks forever, yielding one notification dict per message. Meant
        to run in a background thread for the process lifetime."""
        consumer = KafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            group_id=f"eval-dashboard-{uuid.uuid4()}",
        )
        try:
            for msg in consumer:
                try:
                    yield json.loads(msg.value.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
        finally:
            consumer.close()
