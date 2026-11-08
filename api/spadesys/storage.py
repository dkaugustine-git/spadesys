"""S3-compatible object storage (MinIO locally; S3, R2, etc. elsewhere)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import PurePath
from typing import Any, BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .config import get_settings


@lru_cache
def client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def bucket() -> str:
    return get_settings().s3_bucket


def ensure_bucket() -> None:
    try:
        client().head_bucket(Bucket=bucket())
    except ClientError:
        client().create_bucket(Bucket=bucket())


def new_key(folder: str, filename: str) -> str:
    """Human-readable location, e.g. uploads/2026-11-07/143205_orders.csv"""
    now = datetime.now(timezone.utc)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", PurePath(filename).name) or "file.csv"
    return f"{folder}/{now:%Y-%m-%d}/{now:%H%M%S}_{safe}"


def put(key: str, body: BinaryIO | bytes, content_type: str = "text/csv", original_filename: str | None = None) -> None:
    extra: dict[str, Any] = {}
    if original_filename:
        # S3 metadata must be ASCII
        extra["Metadata"] = {"original-filename": original_filename.encode("ascii", "replace").decode()}
    client().put_object(Bucket=bucket(), Key=key, Body=body, ContentType=content_type, **extra)


def get_bytes(key: str, bucket_name: str | None = None, max_bytes: int | None = None) -> bytes:
    kwargs: dict[str, Any] = {"Bucket": bucket_name or bucket(), "Key": key}
    if max_bytes:
        kwargs["Range"] = f"bytes=0-{max_bytes - 1}"
    return client().get_object(**kwargs)["Body"].read()


def head(key: str, bucket_name: str | None = None) -> dict[str, Any]:
    h = client().head_object(Bucket=bucket_name or bucket(), Key=key)
    return {
        "key": key,
        "size": h["ContentLength"],
        "last_modified": h["LastModified"],
        "content_type": h.get("ContentType"),
        "original_filename": h.get("Metadata", {}).get("original-filename"),
    }


def original_filename(key: str) -> str:
    try:
        name = head(key).get("original_filename")
    except ClientError:
        name = None
    return name or re.sub(r"^\d{6}_", "", PurePath(key).name)


def list_buckets() -> list[str]:
    return [b["Name"] for b in client().list_buckets().get("Buckets", [])]


def list_folder(bucket_name: str, prefix: str) -> dict[str, Any]:
    """One 'folder' level: sub-folders and files directly under prefix."""
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    folders, files = [], []
    paginator = client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix, Delimiter="/"):
        folders += [p["Prefix"] for p in page.get("CommonPrefixes", [])]
        files += [
            {"key": o["Key"], "name": o["Key"][len(prefix):], "size": o["Size"], "last_modified": o["LastModified"]}
            for o in page.get("Contents", [])
            if o["Key"] != prefix
        ]
    return {"bucket": bucket_name, "prefix": prefix, "folders": folders, "files": files}


def stream(key: str, bucket_name: str | None = None):
    return client().get_object(Bucket=bucket_name or bucket(), Key=key)["Body"]
