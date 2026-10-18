from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from . import Blob, PreconditionFailedError

_LOCK = threading.Lock()


class LocalBlobStore:
    """File-system blob store with S3-like semantics (ETags, conditional writes, metadata sidecars)."""

    def __init__(self, url: str) -> None:
        self.url = url
        raw = url.removeprefix("file://")
        self.root = Path(raw).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError(f"key escapes store root: {key}")
        return p

    @staticmethod
    def _etag(data: bytes) -> str:
        return hashlib.md5(data, usedforsecurity=False).hexdigest()

    def get(self, key: str) -> Blob | None:
        p = self._path(key)
        if not p.is_file():
            return None
        data = p.read_bytes()
        return Blob(data=data, etag=self._etag(data))

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
        p = self._path(key)
        with _LOCK:
            current = p.read_bytes() if p.is_file() else None
            if if_none_match and current is not None:
                raise PreconditionFailedError(f"{key} already exists")
            if if_match is not None and (current is None or self._etag(current) != if_match):
                raise PreconditionFailedError(f"{key} changed since it was read")
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            Path(tmp).replace(p)
            meta = {k: v for k, v in {"content_type": content_type, "cache_control": cache_control,
                                       "content_encoding": content_encoding}.items() if v}
            if meta:
                p.with_name(p.name + ".meta.json").write_text(json.dumps(meta))
        return self._etag(data)

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix) if prefix else self.root
        search_root = base if base.is_dir() else base.parent
        if not search_root.exists():
            return []
        keys = []
        for p in search_root.rglob("*"):
            if p.is_file() and not p.name.endswith(".meta.json") and not p.name.startswith(".tmp-"):
                key = p.relative_to(self.root).as_posix()
                if key.startswith(prefix):
                    keys.append(key)
        return sorted(keys)

    def delete(self, key: str) -> None:
        p = self._path(key)
        p.unlink(missing_ok=True)
        p.with_name(p.name + ".meta.json").unlink(missing_ok=True)

    def download_to(self, key: str, path: Path) -> None:
        src = self._path(key)
        if not src.is_file():
            raise FileNotFoundError(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, path)

    def local_path(self, key: str) -> Path | None:
        return self._path(key)
