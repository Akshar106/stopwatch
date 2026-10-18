#!/usr/bin/env bash
# Build the two Lambda deployment packages (docs/contracts.md §1):
#
#   dist/api.zip   = stopwatch + the `ask` extra            (lean: no DuckDB, fast cold starts)
#   dist/jobs.zip  = stopwatch + the `jobs` + `alerts` extras (DuckDB for rollups, pywebpush for notify)
#
# Target: AWS Lambda python3.13 on arm64 (Graviton). Wheels are cross-resolved with uv, so this runs
# on an x86 CI runner or a Mac without Docker/QEMU, and --only-binary=:all: guarantees nothing is
# compiled for the wrong platform. The platform tag is manylinux_2_28, not manylinux2014: psycopg-binary
# (and others) ship aarch64 wheels only for glibc >= 2.27, and the python3.13 runtime is Amazon Linux
# 2023 (glibc 2.34), so every manylinux2014 *and* manylinux_2_28 wheel runs there.
#
# boto3/botocore ARE bundled on purpose: the Lambda runtime's copy lags behind, and S3 conditional
# writes (If-Match / If-None-Match on PutObject, used for the ingest state CAS) need a recent botocore.
#
# Output is reproducible: sorted entries, fixed timestamps and permissions, so the same lockfile and
# source produce the same SHA-256. CI builds once and promotes the identical bytes to staging and prod.
#
# Usage: scripts/package_lambda.sh [api|jobs ...]     (default: both)
# Env:   DIST_DIR (default ./dist), BUILD_DIR (default ./build/lambda), PYTHON (default python3)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
DIST_DIR="${DIST_DIR:-$ROOT/dist}"
BUILD_DIR="${BUILD_DIR:-$ROOT/build/lambda}"
PYTHON="${PYTHON:-python3}"

PLATFORM="${LAMBDA_PLATFORM:-aarch64-manylinux_2_28}"
PY_VERSION="3.13"
MAX_UNZIPPED_BYTES=$((250 * 1024 * 1024)) # Lambda hard limit for an unzipped function + layers

# The only packages allowed to build from an sdist. Each must be pure Python (checked below), so the
# build is platform-independent. http-ece (pywebpush dependency) publishes no wheel at all.
PURE_PYTHON_SDISTS=(http-ece)

die() { echo "package_lambda: $*" >&2; exit 1; }
command -v uv >/dev/null || die "uv is required (https://docs.astral.sh/uv/)"
command -v "$PYTHON" >/dev/null || die "$PYTHON is required to write the zip"
[[ -f "$BACKEND/uv.lock" ]] || die "missing $BACKEND/uv.lock"

# Extras per package. Keep in sync with docs/contracts.md §1 "Packages".
extras_for() {
  case "$1" in
    api) echo "ask" ;;
    jobs) echo "jobs alerts" ;;
    *) die "unknown package '$1' (expected api or jobs)" ;;
  esac
}

build_one() {
  local name="$1"
  local stage="$BUILD_DIR/$name"
  local req="$BUILD_DIR/$name-requirements.txt"
  local zip_path="$DIST_DIR/$name.zip"
  local extra_args=() sdist_args=()
  for extra in $(extras_for "$name"); do extra_args+=(--extra "$extra"); done
  for pkg in "${PURE_PYTHON_SDISTS[@]}"; do sdist_args+=(--no-binary "$pkg"); done

  echo "==> $name: exporting locked requirements (${extra_args[*]})"
  rm -rf "$stage" && mkdir -p "$stage" "$DIST_DIR"
  (cd "$BACKEND" && uv export --frozen --no-dev --no-hashes --no-emit-project \
    "${extra_args[@]}" --output-file "$req" --quiet)

  echo "==> $name: installing wheels for $PLATFORM / CPython $PY_VERSION"
  uv pip install --quiet \
    --target "$stage" \
    --python-platform "$PLATFORM" \
    --python-version "$PY_VERSION" \
    --only-binary=:all: \
    "${sdist_args[@]}" \
    -r "$req"

  # Guard: anything built from source must have produced a pure-Python (py3-none-any) wheel.
  for pkg in "${PURE_PYTHON_SDISTS[@]}"; do
    local wheel_meta
    for wheel_meta in "$stage"/"${pkg//-/_}"-*.dist-info/WHEEL; do
      [[ -f "$wheel_meta" ]] || continue
      grep -q "^Root-Is-Purelib: true" "$wheel_meta" || die "$pkg was built from source but is not pure Python"
    done
  done

  echo "==> $name: adding project source"
  cp -R "$BACKEND/src/stopwatch" "$stage/stopwatch"

  # Trim what Lambda never needs: bytecode caches from the build host's interpreter (not
  # necessarily 3.13), console-script shims, and test suites shipped inside third-party packages.
  find "$stage" -type d -name "__pycache__" -prune -exec rm -rf {} +
  find "$stage" -type f -name "*.py[co]" -delete
  find "$stage" -mindepth 2 -type d \( -name "tests" -o -name "test" \) -prune -exec rm -rf {} +
  rm -rf "$stage/bin"

  if [[ "$name" == "api" && -d "$stage/duckdb" ]]; then
    die "api package must not contain duckdb (cold-start budget, docs/contracts.md §1)"
  fi

  echo "==> $name: writing deterministic zip"
  "$PYTHON" - "$stage" "$zip_path" "$MAX_UNZIPPED_BYTES" <<'PY'
import os
import sys
import zipfile

stage, zip_path, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # earliest DOS timestamp; keeps the archive byte-for-byte stable

files = []
for dirpath, dirnames, filenames in os.walk(stage):
    dirnames.sort()
    for fn in filenames:
        full = os.path.join(dirpath, fn)
        if os.path.islink(full):
            full = os.path.realpath(full)
        files.append((os.path.relpath(os.path.join(dirpath, fn), stage).replace(os.sep, "/"), full))
files.sort()

unzipped = 0
tmp = zip_path + ".tmp"
with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for arcname, full in files:
        info = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3                      # Unix, so the mode bits below are honoured
        info.external_attr = (0o100644 & 0xFFFF) << 16  # regular file, rw-r--r--
        with open(full, "rb") as fh:
            data = fh.read()
        unzipped += len(data)
        zf.writestr(info, data, compresslevel=9)
os.replace(tmp, zip_path)

zipped = os.path.getsize(zip_path)
mb = 1024 * 1024
print(f"    files: {len(files)}  unzipped: {unzipped / mb:.1f} MB  zipped: {zipped / mb:.1f} MB")
if unzipped > limit:
    print(f"ERROR: unzipped size {unzipped / mb:.1f} MB exceeds the Lambda limit of {limit / mb:.0f} MB",
          file=sys.stderr)
    sys.exit(1)
PY

  # Terraform's source_code_hash wants base64(sha256); humans and CI want hex.
  local hex b64
  hex="$("$PYTHON" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$zip_path")"
  b64="$("$PYTHON" -c 'import base64,hashlib,sys;print(base64.b64encode(hashlib.sha256(open(sys.argv[1],"rb").read()).digest()).decode())' "$zip_path")"
  echo "$b64" >"$zip_path.base64sha256"
  echo "    sha256: $hex"
}

targets=("$@")
[[ ${#targets[@]} -eq 0 ]] && targets=(api jobs)
for t in "${targets[@]}"; do build_one "$t"; done

# One checksum file for every artifact in dist/, used to verify promotion between environments.
(cd "$DIST_DIR" && "$PYTHON" - <<'PY'
import hashlib, pathlib
lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
         for p in sorted(pathlib.Path(".").glob("*.zip"))]
pathlib.Path("SHA256SUMS").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
PY
)
echo "==> done: $(ls "$DIST_DIR"/*.zip | tr '\n' ' ')"
