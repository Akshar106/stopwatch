from __future__ import annotations

from pathlib import Path

import boto3
import httpx
import pytest
import respx
from moto import mock_aws

from stopwatch.platform.blobstore import PreconditionFailedError, open_blobstore
from stopwatch.platform.blobstore.s3 import S3BlobStore
from stopwatch.platform.http import FetchError, ResponseTooLargeError, fetch_bytes


def test_local_store_round_trip_and_conditional_writes(tmp_path: Path) -> None:
    store = open_blobstore(f"file://{tmp_path}")
    assert store.get("a/b.txt") is None
    etag = store.put("a/b.txt", b"one", content_type="text/plain")
    with pytest.raises(PreconditionFailedError):
        store.put("a/b.txt", b"x", if_none_match=True)
    with pytest.raises(PreconditionFailedError):
        store.put("a/b.txt", b"x", if_match="stale")
    etag2 = store.put("a/b.txt", b"two", if_match=etag)
    assert store.get("a/b.txt").data == b"two" and etag2 != etag  # type: ignore[union-attr]
    assert store.list("a/") == ["a/b.txt"]
    store.delete("a/b.txt")
    assert store.get("a/b.txt") is None


def test_local_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = open_blobstore(f"file://{tmp_path}/root")
    with pytest.raises(ValueError):
        store.put("../escape.txt", b"x")


@mock_aws
def test_s3_store_round_trip() -> None:
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="lake")
    store = S3BlobStore("s3://lake/prefix", client=client)
    etag = store.put("state/x.json", b"{}", content_type="application/json")
    blob = store.get("state/x.json")
    assert blob is not None and blob.data == b"{}" and blob.etag == etag
    assert store.list("state/") == ["state/x.json"]
    assert client.list_objects_v2(Bucket="lake")["Contents"][0]["Key"] == "prefix/state/x.json"
    assert store.get("missing") is None
    store.delete("state/x.json")
    assert store.list("state/") == []


@respx.mock
def test_fetch_retries_server_errors_then_succeeds() -> None:
    route = respx.get("https://feed.test/x").mock(side_effect=[httpx.Response(503), httpx.Response(200, content=b"ok")])
    assert fetch_bytes("https://feed.test/x", max_bytes=10, retries=2).data == b"ok"
    assert route.call_count == 2


@respx.mock
def test_fetch_enforces_size_cap() -> None:
    respx.get("https://feed.test/big").mock(return_value=httpx.Response(200, content=b"x" * 100))
    with pytest.raises(ResponseTooLargeError):
        fetch_bytes("https://feed.test/big", max_bytes=10)


@respx.mock
def test_fetch_does_not_follow_redirects_or_retry_client_errors() -> None:
    route = respx.get("https://feed.test/r").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )
    with pytest.raises(FetchError, match="not retried"):
        fetch_bytes("https://feed.test/r", max_bytes=10, retries=3)
    assert route.call_count == 1


@respx.mock
def test_fetch_conditional_get() -> None:
    respx.get("https://feed.test/zip").mock(return_value=httpx.Response(304, headers={"etag": '"abc"'}))
    r = fetch_bytes("https://feed.test/zip", max_bytes=10, if_none_match='"abc"')
    assert r.not_modified and r.status == 304
