#!/usr/bin/env bash
# Upload a built us-boundaries catalog to Source Cooperative, then check every file is live.
#
#   scripts/publish.sh <built catalog dir> [--dry-run]
#
# Order: GeoParquet and PMTiles first, then item/collection metadata, then versions.json and manifest.json, and
# the root catalog.json last, so a reader never sees metadata that names files not yet uploaded.
# Needs the `source-coop` AWS profile (see README: `source-coop login`); credentials never leave
# this machine. Refuses to run if the repo's metadata differs from the build (commit it first).
set -euo pipefail

OUT=${1:?usage: scripts/publish.sh <built catalog dir> [--dry-run]}
DRY=${2:-}
DEST=s3://nthh/us-boundaries
PUBLIC=https://data.source.coop/nthh/us-boundaries
REPO=$(cd "$(dirname "$0")/.." && pwd)
export AWS_PROFILE=${AWS_PROFILE:-source-coop}

# The repo must mirror the build (everything but the GeoParquet), and be committed.
if ! diff -rq -x '*.parquet' -x '*.pmtiles' -x .git -x scripts -x LICENSE -x .gitignore "$OUT" "$REPO" >/dev/null; then
  diff -rq -x '*.parquet' -x '*.pmtiles' -x .git -x scripts -x LICENSE -x .gitignore "$OUT" "$REPO" | head -20
  echo "repo metadata differs from $OUT; copy it in and commit before publishing" >&2
  exit 1
fi
if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
  echo "repo has uncommitted changes; commit before publishing" >&2
  exit 1
fi

sync() { aws s3 sync "$OUT" "$DEST" --only-show-errors --no-progress ${DRY:+--dryrun} "$@"; }

echo "1/4 GeoParquet and PMTiles"
sync --exclude '*' --include '*.parquet' --include '*.pmtiles'
echo "2/4 items, collections, READMEs, styles, thumbnails, build script"
sync --exclude '*.parquet' --exclude '*.pmtiles' --exclude '*/versions.json' --exclude '*/manifest.json' --exclude 'catalog.json'
aws s3 cp "$REPO/scripts/build_sorted_boundary_partitions.py" "$DEST/scripts/build_sorted_boundary_partitions.py" \
  --only-show-errors ${DRY:+--dryrun}
echo "3/4 versions.json and manifest.json"
sync --exclude '*' --include '*/versions.json' --include '*/manifest.json'
echo "4/4 root catalog.json"
sync --exclude '*' --include 'catalog.json'

[ -n "$DRY" ] && { echo "dry run: nothing uploaded"; exit 0; }

echo "checking every manifest entry at $PUBLIC"
python3 - "$OUT" "$PUBLIC" <<'EOF'
import concurrent.futures, hashlib, json, sys, urllib.request
from pathlib import Path

out, public = Path(sys.argv[1]), sys.argv[2]
UA = {"User-Agent": "us-boundaries-publish/1"}
checks = []
for manifest in sorted(out.glob("*/manifest.json")):
    ds = manifest.parent.name
    for rel, f in json.loads(manifest.read_text())["files"].items():
        checks.append((f"{ds}/{rel}", f["bytes"], f["sha256"]))
for name in ("catalog.json", "README.md", "AGENTS.md"):
    p = out / name
    checks.append((name, p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()))


def check(c):
    rel, size, sha = c
    url = f"{public}/{rel}"
    head = urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA))
    live = int(head.headers["Content-Length"])
    if live != size:
        return f"{rel}: {live} bytes live, {size} built"
    if size < 5_000_000:  # small files: compare content too
        body = urllib.request.urlopen(urllib.request.Request(url, headers=UA)).read()
        if hashlib.sha256(body).hexdigest() != sha:
            return f"{rel}: sha256 differs"
    return None


with concurrent.futures.ThreadPoolExecutor(16) as pool:
    bad = [r for r in pool.map(check, checks) if r]
print(f"{len(checks)} files checked, {len(bad)} problems")
for b in bad:
    print(" ", b)
sys.exit(1 if bad else 0)
EOF
