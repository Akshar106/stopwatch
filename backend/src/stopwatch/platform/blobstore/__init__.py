"""Object storage behind one small interface: S3 in the cloud, the local file system in development."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class PreconditionFailedError(Exception):
    """A conditional write (If-Match / If-None-Match) lost a race or found unexpected state."""


@dataclass(frozen=True)
class Blob:
    data: bytes
    etag: str


class BlobStore(Protocol):
    url: str

    def get(self, key: str) -> Blob | None: ...

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
    ) -> str: ...

    def list(self, prefix: str) -> list[str]: ...

    def delete(self, key: str) -> None: ...

    def download_to(self, key: str, path: Path) -> None: ...

    def local_path(self, key: str) -> Path | None:
        """Direct path for file-backed stores (lets DuckDB read in place); None for remote stores."""
        ...


def open_blobstore(url: str) -> BlobStore:
    if url.startswith("file://"):
        from .local import LocalBlobStore

        return LocalBlobStore(url)
    if url.startswith("s3://"):
        from .s3 import S3BlobStore

        return S3BlobStore(url)
    raise ValueError(f"unsupported blobstore url: {url}")


__all__ = ["Blob", "BlobStore", "PreconditionFailedError", "open_blobstore"]
