"""Atomic publishing of immutable builds with a manifest swap, retention, and one-command rollback.

python -m stopwatch.rollups.publish --list
python -m stopwatch.rollups.publish --rollback 20261019T081502Z
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from stopwatch.platform.blobstore import BlobStore

BUILDS_PREFIX = "data/v1/builds/"
MANIFEST_KEY = "data/v1/manifest.json"
KEEP_BUILDS = 14
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=60"


def agency_paths(build_id: str, agency_id: str, has_validation: bool) -> dict[str, Any]:
    base = f"/data/v1/builds/{build_id}/{agency_id}"
    return {
        "stops": f"{base}/stops.json",
        "routes": f"{base}/routes.json",
        "route_template": f"{base}/routes/{{route_id}}.json",
        "coverage": f"{base}/coverage.json",
        "health": f"/data/v1/health/{agency_id}.json",
        "validation": f"/data/v1/validation/{agency_id}.json" if has_validation else None,
    }


def build_manifest(build_id: str, generated_at: str, agencies: list[dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for a in agencies:
        has_validation = bool(a.get("_has_validation"))
        entry = {k: v for k, v in a.items() if not k.startswith("_")}
        entry["paths"] = agency_paths(build_id, a["id"], has_validation)
        entries.append(entry)
    return {"schema_version": 1, "build_id": build_id, "generated_at": generated_at, "agencies": entries}


def list_builds(site: BlobStore) -> list[str]:
    ids = {k[len(BUILDS_PREFIX) :].split("/", 1)[0] for k in site.list(BUILDS_PREFIX)}
    return sorted(i for i in ids if i)


def publish(site: BlobStore, build_id: str, files: dict[str, bytes], manifest: dict[str, Any]) -> None:
    """Upload every file of the build first, then swap the manifest last (readers never see half a build)."""
    for rel, data in files.items():
        site.put(f"{BUILDS_PREFIX}{build_id}/{rel}", data, content_type="application/json", cache_control=IMMUTABLE)
    body = json.dumps(manifest, separators=(",", ":")).encode()
    site.put(f"{BUILDS_PREFIX}{build_id}/build.json", body, content_type="application/json", cache_control=IMMUTABLE)
    site.put(MANIFEST_KEY, body, content_type="application/json", cache_control=SHORT)
    prune(site, keep=KEEP_BUILDS, protect=build_id)


def prune(site: BlobStore, *, keep: int, protect: str) -> list[str]:
    builds = list_builds(site)
    doomed = [b for b in builds[:-keep] if b != protect] if len(builds) > keep else []
    for b in doomed:
        for key in site.list(f"{BUILDS_PREFIX}{b}/"):
            site.delete(key)
    return doomed


def rollback(site: BlobStore, build_id: str) -> dict[str, Any]:
    blob = site.get(f"{BUILDS_PREFIX}{build_id}/build.json")
    if blob is None:
        raise SystemExit(f"build {build_id} not found (available: {', '.join(list_builds(site)) or 'none'})")
    site.put(MANIFEST_KEY, blob.data, content_type="application/json", cache_control=SHORT)
    manifest: dict[str, Any] = json.loads(blob.data)
    return manifest


def main() -> int:
    from stopwatch.platform.blobstore import open_blobstore
    from stopwatch.platform.config import get_settings

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rollback", metavar="BUILD_ID")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    site = open_blobstore(get_settings().site_url)
    if args.rollback:
        m = rollback(site, args.rollback)
        print(f"manifest now points at {m['build_id']}")
    else:
        current = site.get(MANIFEST_KEY)
        live = json.loads(current.data)["build_id"] if current else None
        for b in list_builds(site):
            print(f"{b}{'  <- live' if b == live else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
