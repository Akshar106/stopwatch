"""Outbound HTTP for untrusted upstreams: strict timeouts, size caps, no cross-host redirects, bounded retries."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx


class FetchError(Exception):
    pass


class ResponseTooLargeError(FetchError):
    pass


@dataclass(frozen=True)
class FetchResult:
    data: bytes
    status: int
    etag: str | None
    last_modified: str | None
    not_modified: bool = False


USER_AGENT = "stopwatch/0.1 (+https://github.com/; transit reliability research; polite 1 req/min)"


def fetch_bytes(
    url: str,
    *,
    max_bytes: int,
    connect_timeout: float = 3.0,
    read_timeout: float = 10.0,
    retries: int = 2,
    deadline: float | None = None,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
    client: httpx.Client | None = None,
) -> FetchResult:
    """GET ``url`` with a hard byte cap. Retries idempotent failures with full-jitter backoff within ``deadline``.

    ``deadline`` is an absolute ``time.monotonic()`` value; no attempt starts after it.
    """
    headers = {"User-Agent": USER_AGENT}
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since
    timeout = httpx.Timeout(read_timeout, connect=connect_timeout)
    own_client = client is None
    c = client or httpx.Client(timeout=timeout, follow_redirects=False)
    last_exc: Exception | None = None
    try:
        for attempt in range(retries + 1):
            if deadline is not None and time.monotonic() >= deadline:
                break
            try:
                with c.stream("GET", url, headers=headers, timeout=timeout) as resp:
                    if resp.status_code == 304:
                        return FetchResult(b"", 304, resp.headers.get("etag"), resp.headers.get("last-modified"), True)
                    if resp.status_code >= 500 or resp.status_code == 429:
                        raise FetchError(f"{url}: HTTP {resp.status_code}")
                    if resp.status_code != 200:
                        # 3xx/4xx are not retried: a redirect to another host or a client error won't fix itself.
                        raise FetchError(f"{url}: HTTP {resp.status_code} (not retried)")
                    declared = resp.headers.get("content-length")
                    if declared and int(declared) > max_bytes:
                        raise ResponseTooLargeError(f"{url}: {declared} bytes > {max_bytes}")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ResponseTooLargeError(f"{url}: > {max_bytes} bytes")
                        chunks.append(chunk)
                    return FetchResult(b"".join(chunks), 200, resp.headers.get("etag"),
                                       resp.headers.get("last-modified"))
            except ResponseTooLargeError:
                raise
            except FetchError as exc:
                last_exc = exc
                if "(not retried)" in str(exc):
                    raise
            except httpx.HTTPError as exc:
                last_exc = FetchError(f"{url}: {type(exc).__name__}: {exc}")
            if attempt < retries:
                backoff = random.uniform(0, min(4.0, 0.5 * 2**attempt))  # noqa: S311 - jitter, not crypto
                if deadline is not None:
                    backoff = min(backoff, max(0.0, deadline - time.monotonic()))
                time.sleep(backoff)
    finally:
        if own_client:
            c.close()
    raise last_exc or FetchError(f"{url}: deadline exceeded before first attempt")
