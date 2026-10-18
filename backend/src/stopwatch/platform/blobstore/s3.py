from __future__ import annotations

from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from . import Blob, PreconditionFailedError

_PRECONDITION_CODES = {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}


class S3BlobStore:
    """S3 blob store. Conditional writes use S3's native If-Match / If-None-Match support."""

    def __init__(self, url: str, client: Any | None = None) -> None:
        self.url = url
        rest = url.removeprefix("s3://")
        bucket, _, prefix = rest.partition("/")
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self.client = client or boto3.client(
            "s3", config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=3, read_timeout=10)
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get(self, key: str) -> Blob | None:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
        return Blob(data=resp["Body"].read(), etag=resp["ETag"].strip('"'))

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        cache_control: str | None = None,
        content_encoding: str | None = None,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": self._key(key), "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        if cache_control:
            kwargs["CacheControl"] = cache_control
        if content_encoding:
            kwargs["ContentEncoding"] = content_encoding
        if if_match:
            kwargs["IfMatch"] = f'"{if_match}"'
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        try:
            resp = self.client.put_object(**kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            status = str(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
            if code in _PRECONDITION_CODES or status in ("412", "409"):
                raise PreconditionFailedError(f"{key}: {code or status}") from exc
            raise
        return str(resp["ETag"]).strip('"')

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._key(prefix)):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"][len(self.prefix) :])
        return sorted(keys)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def download_to(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, self._key(key), str(path))

    def local_path(self, key: str) -> Path | None:
        return None
