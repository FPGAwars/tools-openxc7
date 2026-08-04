#!/usr/bin/env bash
#
# asset-check.sh -- verify the published release assets EXACTLY the way
# apio will look for them, without installing apio.
#
# apio derives everything from the release TAG: tag 2026-06-13 -> date
# 20260613 -> asset apio-openxc7-<platform>-20260613.tgz at that release's
# download URL. A mistagged release, a misdated asset name or a missing
# platform is a 404 at `apio packages install` time on that platform (the
# 2026-07-24 class of failure: remote-config pointed at a tag whose release
# was never published). This script chases exactly that: it recomputes the
# URL by apio's rule and checks what is actually there.
#
# Usage:
#   scripts/asset-check.sh <tag>                     # existence + SHA256SUMS
#   scripts/asset-check.sh <tag> --expect-dir DIR    # local tarballs must match
#                                                    # the published SHA256SUMS
#   scripts/asset-check.sh <tag> --full              # download + hash for real
#                                                    # (for releases without
#                                                    # SHA256SUMS; slow)
#   scripts/asset-check.sh <tag> --platform linux-x86-64   # repeatable filter
#
# Env: ASSET_CHECK_REPO to point at a fork (default FPGAwars/tools-openxc7);
#      GH_TOKEN / GITHUB_TOKEN are used if set (API rate limits).

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TAG="" EXPECT_DIR="" FULL=0 PLATFORMS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --expect-dir) EXPECT_DIR="$2"; shift 2 ;;
        --full) FULL=1; shift ;;
        --platform) PLATFORMS+=("$2"); shift 2 ;;
        -h|--help) sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) TAG="$1"; shift ;;
    esac
done
[ -n "$TAG" ] || { echo "usage: scripts/asset-check.sh <tag> [--expect-dir DIR] [--full] [--platform p]..." >&2; exit 2; }
[ ${#PLATFORMS[@]} -gt 0 ] || PLATFORMS=(linux-x86-64 darwin-arm64 windows-amd64)

python3 - "$TAG" "$EXPECT_DIR" "$FULL" "${PLATFORMS[@]}" <<'PYEOF'
import hashlib, os, sys, urllib.error, urllib.request

tag, expect_dir, full = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
platforms = sys.argv[4:]
repo = os.environ.get("ASSET_CHECK_REPO", "FPGAwars/tools-openxc7")
date = tag.replace("-", "")
base = f"https://github.com/{repo}/releases/download/{tag}"
failed = []


def request(url, method="GET"):
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": "tools-openxc7-asset-check"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=60)


def head(url):
    """(status, size) following redirects — GitHub serves assets via S3."""
    try:
        with request(url, method="HEAD") as resp:
            return resp.status, int(resp.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as exc:
        return exc.code, 0


def sha256_stream(resp):
    h = hashlib.sha256()
    for chunk in iter(lambda: resp.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


# The published SHA256SUMS (release.yml uploads it). Optional: manual
# releases predate it — existence checks still run without one.
sums = {}
try:
    with request(f"{base}/SHA256SUMS") as resp:
        for line in resp.read().decode().splitlines():
            parts = line.split()
            if len(parts) == 2:
                sums[parts[1].lstrip("*")] = parts[0]
    print(f"SHA256SUMS: {len(sums)} entries")
except urllib.error.HTTPError:
    print("SHA256SUMS: not published on this release (pre-release.yml era)")

for platform in platforms:
    asset = f"apio-openxc7-{platform}-{date}.tgz"
    url = f"{base}/{asset}"
    status, size = head(url)
    if status != 200:
        print(f"❌ {asset}: HTTP {status} at {url}")
        print(f"   apio WILL 404 on {platform}: the asset for tag {tag} must be")
        print(f"   named with the tag's date ({date}) and live at that release.")
        failed.append(asset)
        continue
    line = f"✅ {asset}: HTTP 200 ({size / 1e6:.0f} MB)"

    published = sums.get(asset)
    if published is None and sums:
        print(f"❌ {asset}: published but MISSING from SHA256SUMS")
        failed.append(asset)
        continue

    if expect_dir:
        local = os.path.join(expect_dir, asset)
        if not os.path.exists(local):
            print(f"❌ {asset}: --expect-dir has no such file ({local})")
            failed.append(asset)
            continue
        with open(local, "rb") as fh:
            local_sha = sha256_stream(fh)
        if published is not None:
            if local_sha != published:
                print(f"❌ {asset}: local sha256 {local_sha[:12]}… != published SHA256SUMS {published[:12]}…")
                print("   the uploaded asset is NOT the package that was validated")
                failed.append(asset)
                continue
            line += " · sha256 == SHA256SUMS == local"
        elif full:
            with request(url) as resp:
                remote_sha = sha256_stream(resp)
            if remote_sha != local_sha:
                print(f"❌ {asset}: downloaded sha256 {remote_sha[:12]}… != local {local_sha[:12]}…")
                failed.append(asset)
                continue
            line += " · sha256(downloaded) == local"
        else:
            line += f" · local sha256 {local_sha[:12]}… (no SHA256SUMS to compare; use --full)"
    elif full:
        with request(url) as resp:
            remote_sha = sha256_stream(resp)
        if published is not None and remote_sha != published:
            print(f"❌ {asset}: downloaded sha256 {remote_sha[:12]}… != SHA256SUMS {published[:12]}…")
            failed.append(asset)
            continue
        line += f" · sha256(downloaded) {remote_sha[:12]}…" + (" == SHA256SUMS" if published else "")

    print(line)

if failed:
    print(f"\nasset-check: FAIL ({len(failed)}: {', '.join(failed)})")
    sys.exit(1)
print("\nasset-check: OK — apio's URL rule resolves for every platform")
PYEOF
