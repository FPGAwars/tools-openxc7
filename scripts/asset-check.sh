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
# Since the on-demand chipdb (apio#947) that is no longer only the three
# platform tarballs. The packages ship no device database: apio reads
# CHIPDB-INFO.json, resolves the asset for the board's FPGA and downloads
# it from the same release. A missing or truncated per-FPGA asset is a
# user who cannot build for that board, and the release gate must see it,
# so this script also validates the published document and every asset it
# declares. A release without that document predates the model and is
# reported as legacy, not failed.
#
# Usage:
#   scripts/asset-check.sh <tag>                     # existence + SHA256SUMS
#                                                    # + chipdb document/assets
#   scripts/asset-check.sh <tag> --expect-dir DIR    # local tarballs must match
#                                                    # the published SHA256SUMS
#   scripts/asset-check.sh <tag> --full              # download + hash for real
#                                                    # (tarballs without
#                                                    # SHA256SUMS, and every
#                                                    # chipdb asset: ~830 MB)
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
        -h|--help) sed -n '3,35p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) TAG="$1"; shift ;;
    esac
done
[ -n "$TAG" ] || { echo "usage: scripts/asset-check.sh <tag> [--expect-dir DIR] [--full] [--platform p]..." >&2; exit 2; }
[ ${#PLATFORMS[@]} -gt 0 ] || PLATFORMS=(linux-x86-64 darwin-arm64 windows-amd64)

python3 - "$REPO_ROOT" "$TAG" "$EXPECT_DIR" "$FULL" "${PLATFORMS[@]}" <<'PYEOF'
import hashlib, json, os, sys, tarfile, tempfile, urllib.error, urllib.request
from pathlib import Path

repo_root, tag, expect_dir = sys.argv[1], sys.argv[2], sys.argv[3]
full = sys.argv[4] == "1"
platforms = sys.argv[5:]

# The document is validated by the SAME code that writes it (one validator,
# used by L1 on a package and here on a release).
sys.path.insert(0, repo_root)
from pack.chipdb_info import SCHEMA, info_asset_name, validate_document  # noqa: E402

repo = os.environ.get("ASSET_CHECK_REPO", "FPGAwars/tools-openxc7")
date = tag.replace("-", "")
base = f"https://github.com/{repo}/releases/download/{tag}"
failed = []


def request(url, method="GET"):
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": "tools-openxc7-asset-check"})
    # Authorization ONLY for api.github.com. Release download URLs redirect
    # to signed blob storage, and urllib FORWARDS the Authorization header to
    # the redirect target -- which rejects the double auth (HTTP 401). That
    # broke the in-CI verification (token set) while the same check passed
    # anonymously. Public downloads need no token; apio fetches them bare too.
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
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


# The published SHA256SUMS (build-pre-release.yaml uploads it). Optional: manual
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
    print("SHA256SUMS: not published on this release (pre-build-pre-release era)")

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


# ---------------------------------------------------------------------------
# The on-demand chipdb: the document, and every per-FPGA asset it declares.
# ---------------------------------------------------------------------------
def check_chipdb_asset(part, entry):
    """Verify one per-FPGA asset against what the document promises."""
    asset = entry["asset"]
    url = f"{base}/{asset}"
    status, size = head(url)
    if status != 200:
        print(f"❌ {asset}: HTTP {status} — declared by the document, not in the release")
        print(f"   apio WILL 404 for {part}: no board using that FPGA can build.")
        failed.append(asset)
        return
    if size != entry["tgz_size"]:
        print(f"❌ {asset}: {size} bytes published, document says {entry['tgz_size']}")
        print("   the uploaded asset is NOT the one the document describes")
        failed.append(asset)
        return
    line = f"✅ {asset}: HTTP 200 ({size / 1e6:.0f} MB == tgz_size)"

    if full:
        with tempfile.TemporaryDirectory() as scratch:
            blob = Path(scratch) / asset
            digest = hashlib.sha256()
            with request(url) as resp, blob.open("wb") as out:
                for chunk in iter(lambda: resp.read(1 << 20), b""):
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != entry["tgz_sha256"]:
                print(f"❌ {asset}: downloaded sha256 {digest.hexdigest()[:12]}… "
                      f"!= document tgz_sha256 {entry['tgz_sha256'][:12]}…")
                failed.append(asset)
                return
            # And what the loader ends up with on disk: the .bin inside.
            try:
                with tarfile.open(blob) as archive:
                    member = archive.getmember(f"{part}.bin")
                    if member.size != entry["size"]:
                        print(f"❌ {asset}: {part}.bin is {member.size} bytes, "
                              f"document says {entry['size']}")
                        failed.append(asset)
                        return
                    inner = hashlib.sha256()
                    with archive.extractfile(member) as source:
                        for chunk in iter(lambda: source.read(1 << 20), b""):
                            inner.update(chunk)
            except (KeyError, tarfile.TarError) as error:
                print(f"❌ {asset}: does not carry {part}.bin at its root ({error})")
                failed.append(asset)
                return
            if inner.hexdigest() != entry["sha256"]:
                print(f"❌ {asset}: {part}.bin sha256 {inner.hexdigest()[:12]}… "
                      f"!= document sha256 {entry['sha256'][:12]}…")
                failed.append(asset)
                return
        line += f" · sha256 == document · {part}.bin {entry['size']} B verified"
    print(line)


def check_chipdb_release():
    """Validate the published document and every asset it declares.

    Returns how many per-FPGA assets were verified (0 on a legacy release).
    """
    info_asset = info_asset_name(date)
    try:
        with request(f"{base}/{info_asset}") as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        print(f"— {info_asset}: not published (HTTP 404)")
        print("  legacy release: packages carry the chipdb, no per-FPGA assets")
        return 0

    try:
        info = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        print(f"❌ {info_asset}: not readable as JSON ({error})")
        failed.append(info_asset)
        return 0

    # Schema 3 IS the on-demand contract: the document apio's loader reads to
    # find the asset for a board's FPGA, written by the same run that builds
    # the packages (pack/chipdb_assets.py, where SCHEMA is a constant, so a
    # current run cannot produce an older one). Only releases from before that
    # model carry an older document, and there the per-FPGA assets are a bonus:
    # the packages ship the chipdb themselves, so a gap cannot break a user.
    # Reported, never failed.
    if info.get("schema") != SCHEMA:
        print(f"— {info_asset}: schema {info.get('schema')!r}, not {SCHEMA}")
        print("  legacy release: packages carry the chipdb, per-FPGA assets are"
              " not what apio installs from")
        return 0

    try:
        generated = validate_document(info, expect_tag=tag)
    except ValueError as error:
        print(f"❌ {info_asset}: {error}")
        print("   apio's on-demand loader reads this document: a release whose")
        print("   map is wrong points every download at the wrong place.")
        failed.append(info_asset)
        return 0

    print(f"✅ {info_asset}: HTTP 200 ({len(raw)} B) · schema {info['schema']}"
          f" · release-tag {info['release-tag']} · chipdb-id {info['chipdb-id']}"
          f" · {info['generated-count']} generated of {info['available-count']}")
    for part, entry in sorted(generated.items()):
        check_chipdb_asset(part, entry)
    return len(generated)


checked_chipdb = check_chipdb_release()

if failed:
    print(f"\nasset-check: FAIL ({len(failed)}: {', '.join(failed)})")
    sys.exit(1)
tail = (f" and for the {checked_chipdb} chipdb assets of this release"
        if checked_chipdb else "")
print(f"\nasset-check: OK — apio's URL rule resolves for every platform{tail}")
PYEOF
