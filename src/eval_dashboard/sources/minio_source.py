"""Reads full episode records from MinIO.

Read-only: only ListObjectsV2 and GetObject are ever called. MinIO is the
authoritative record store in this design -- Kafka only carries a
change-notification (episode_id + s3_uri); when one arrives, the caller
resolves it back to a full record with `get_by_uri`. `list_bucket` powers
the full-replay path (startup, and the periodic episodes-rejected poll,
since rejects never get a Kafka notification of their own).

Storage is ephemeral per the brief, so an empty bucket is a normal, handled
case -- `list_bucket` just yields nothing.
"""
from __future__ import annotations

import json
from typing import Iterator
from urllib.parse import urlparse

import boto3

from eval_dashboard import schema


class MinioSource:
    def __init__(self, endpoint: str, access_key: str, secret_key: str):
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def list_bucket(self, bucket: str) -> Iterator[dict]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                normalized = self._get(bucket, obj["Key"])
                if normalized:
                    yield normalized

    def get_by_uri(self, s3_uri: str) -> dict | None:
        parsed = urlparse(s3_uri)
        return self._get(parsed.netloc, parsed.path.lstrip("/"))

    def _get(self, bucket: str, key: str) -> dict | None:
        try:
            body = self._client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception:
            return None
        try:
            raw = json.loads(body)
        except json.JSONDecodeError:
            return None
        return schema.normalize(raw)
