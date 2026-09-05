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
# XILINX-PARTS-INDEX.json, resolves the asset for the board's part and
# downloads it from the same release. A missing or truncated per-FPGA asset is a
# user who cannot build for that board, and the release gate must see it,
# so this script also validates the published index and every asset it
# declares. Several parts (the speed grades of one base part) share an
# asset, so the assets are checked once each, not once per part. A
# release whose index is not the one apio reads today -- absent under
# every name it has been published with, or an older schema -- predates
# this contract and is reported as legacy, not failed: it is not what
# apio installs from.
#
# SHA256SUMS covers every asset since apio#990 (it used to list only the
# three packages). Where it and the index both describe an asset, the two
# documents are required to agree, which is the whole point of writing
# them from the same bytes in the same job: the hash comparison itself
# happens once, against the index, and never twice over the same bytes.
#
# Usage:
#   scripts/asset-check.sh <tag>                     # existence + SHA256SUMS
#                                                    # + parts index and assets
#   scripts/asset-check.sh <tag> --expect-dir DIR    # local tarballs must match
#                                                    # the published SHA256SUMS
#   scripts/asset-check.sh <tag> --full              # download + hash for real
#                                                    # (tarballs without
#                                                    # SHA256SUMS, and every
#                                                    # chipdb asset: ~2 GB)
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
        -h|--help) sed -n '3,42p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) TAG="$1"; shift ;;
    esac
done
[ -n "$TAG" ] || { echo "usage: scripts/asset-check.sh <tag> [--expect-dir DIR] [--full] [--platform p]..." >&2; exit 2; }
[ ${#PLATFORMS[@]} -gt 0 ] || PLATFORMS=(linux-x86-64 darwin-arm64 windows-amd64)

python3 - "$REPO_ROOT" "$TAG" "$EXPECT_DIR" "$FULL" "${PLATFORMS[@]}" <<'PYEOF'
import hashlib, json, os, sys, tarfile, tempfile, time
import urllib.error, urllib.request
from pathlib import Path

repo_root, tag, expect_dir = sys.argv[1], sys.argv[2], sys.argv[3]
full = sys.argv[4] == "1"
platforms = sys.argv[5:]

# The index is validated by the SAME code that writes it (one validator,
# used by L1 on a package and here on a release).
sys.path.insert(0, repo_root)
from pack.parts_index import (INDEX_ASSET, SCHEMA,  # noqa: E402
                              previous_index_asset_names, validate_document)

repo = os.environ.get("ASSET_CHECK_REPO", "FPGAwars/tools-openxc7")
date = tag.replace("-", "")
base = f"https://github.com/{repo}/releases/download/{tag}"
failed = []


def request(url, method="GET", attempts=3):
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
    # A transient connection failure is not an answer about the release, and
    # this check now makes one request per published asset -- about fifty on
    # a full-manifest release, ~2 GB with --full. Retried, with a pause; an
    # HTTPError is NOT retried, because 404 is the answer we came for.
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if attempt == attempts:
                raise
            print(f"   … {url.rsplit('/', 1)[-1]}: {error}, retrying "
                  f"({attempt}/{attempts - 1})")
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


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

# Does this manifest cover the whole release or only the packages? Until
# apio#990 it listed the three tarballs alone, and requiring the chipdb
# assets of such a release would fail one that was complete when it was
# made. Anything that is not a platform package marks the wider manifest.
covers_everything = any(not name.startswith("apio-openxc7-") for name in sums)
if sums and not covers_everything:
    print("   the platform packages only: published before SHA256SUMS "
          "covered the chipdb assets")

# Every name this run looked at, to catch a manifest line describing an
# asset the release does not have (checked at the end).
accounted = set()

for platform in platforms:
    asset = f"apio-openxc7-{platform}-{date}.tgz"
    accounted.add(asset)
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
# The on-demand chipdb: the parts index, and every per-FPGA asset it names.
# ---------------------------------------------------------------------------
def check_chipdb_asset(asset, entry, parts):
    """Verify one per-FPGA asset against what the index promises.

    *parts* are the parts served by it — the speed grades of one base
    part share a file, so one asset answers for several of them.
    """
    chipdb = entry["chipdb"]
    accounted.add(asset)
    url = f"{base}/{asset}"
    status, size = head(url)
    if status != 200:
        print(f"❌ {asset}: HTTP {status} — named by the index, not in the release")
        print(f"   apio WILL 404 for {', '.join(parts)}: no board using that")
        print("   FPGA can build.")
        failed.append(asset)
        return
    if size != entry["asset-size"]:
        print(f"❌ {asset}: {size} bytes published, index says {entry['asset-size']}")
        print("   the uploaded asset is NOT the one the index describes")
        failed.append(asset)
        return
    line = (f"✅ {asset}: HTTP 200 ({size / 1e6:.0f} MB == asset-size)"
            f" · {len(parts)} parts")

    # The two documents of the release describe this asset; they are
    # written in the same job from the same bytes, so they must agree.
    # Comparing them costs no download, and it is the whole verification
    # SHA256SUMS adds here: the bytes themselves are hashed once, below,
    # against the index.
    if covers_everything:
        published = sums.get(asset)
        if published is None:
            print(f"❌ {asset}: named by the index, MISSING from SHA256SUMS")
            failed.append(asset)
            return
        if published != entry["asset-sha256"]:
            print(f"❌ {asset}: SHA256SUMS says {published[:12]}…, the index "
                  f"says {entry['asset-sha256'][:12]}…")
            print("   the release's two documents describe different bytes")
            failed.append(asset)
            return
        line += " · sha256 == SHA256SUMS"

    if full:
        with tempfile.TemporaryDirectory() as scratch:
            blob = Path(scratch) / asset
            digest = hashlib.sha256()
            with request(url) as resp, blob.open("wb") as out:
                for chunk in iter(lambda: resp.read(1 << 20), b""):
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != entry["asset-sha256"]:
                print(f"❌ {asset}: downloaded sha256 {digest.hexdigest()[:12]}… "
                      f"!= index asset-sha256 {entry['asset-sha256'][:12]}…")
                failed.append(asset)
                return
            # And what the loader ends up with on disk: the chipdb inside.
            try:
                with tarfile.open(blob) as archive:
                    member = archive.getmember(chipdb)
                    if member.size != entry["chipdb-size"]:
                        print(f"❌ {asset}: {chipdb} is {member.size} bytes, "
                              f"index says {entry['chipdb-size']}")
                        failed.append(asset)
                        return
                    inner = hashlib.sha256()
                    with archive.extractfile(member) as source:
                        for chunk in iter(lambda: source.read(1 << 20), b""):
                            inner.update(chunk)
            except (KeyError, tarfile.TarError) as error:
                print(f"❌ {asset}: does not carry {chipdb} at its root ({error})")
                failed.append(asset)
                return
            if inner.hexdigest() != entry["chipdb-sha256"]:
                print(f"❌ {asset}: {chipdb} sha256 {inner.hexdigest()[:12]}… "
                      f"!= index chipdb-sha256 {entry['chipdb-sha256'][:12]}…")
                failed.append(asset)
                return
        line += (f" · sha256 == index · {chipdb} "
                 f"{entry['chipdb-size']} B verified")
    print(line)


def fetch_index():
    """The published index document: (asset name, bytes), or (None, None).

    Published as XILINX-PARTS-INDEX.json since the apio#1002 rename -- the
    name it also has inside every package, because which release it belongs
    to is written in the document, not in its file name. Earlier releases
    carry it as PARTS-INDEX.json (apio#990) and, up to 2026-08-31, under
    the dated name; apio's loader accepts every one, so this gate reads
    them all rather than calling those releases legacy.
    """
    for asset in [INDEX_ASSET, *previous_index_asset_names(date)]:
        try:
            with request(f"{base}/{asset}") as resp:
                return asset, resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    return None, None


def check_chipdb_release():
    """Validate the published parts index and every asset it names.

    Returns how many per-FPGA assets were verified (0 on a legacy release).
    """
    index_asset, raw = fetch_index()
    if index_asset is None:
        print(f"— {INDEX_ASSET}: not published (HTTP 404)")
        print("  legacy release: no parts index under any of the names apio"
              " has resolved, so the on-demand contract this gate checks is"
              " not the one that release was published under")
        return 0
    accounted.add(index_asset)

    try:
        info = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        print(f"❌ {index_asset}: not readable as JSON ({error})")
        failed.append(index_asset)
        return 0

    # This schema IS the on-demand contract: the index apio's loader reads to
    # find the asset for a board's part, written by the same run that builds
    # the packages (pack/parts_index.py, where SCHEMA is a constant, so a
    # current run cannot produce an older one). An older one is a release from
    # before that contract, and what its assets mean is its own gate's
    # business, not this one's. Reported, never failed.
    if info.get("schema") != SCHEMA:
        print(f"— {index_asset}: schema {info.get('schema')!r}, not {SCHEMA}")
        print("  legacy release: an index older than the contract this gate"
              " checks, so its assets are not what apio installs from today")
        return 0

    try:
        generated = validate_document(info, expect_tag=tag)
    except ValueError as error:
        print(f"❌ {index_asset}: {error}")
        print("   apio's on-demand loader reads this index: a release whose")
        print("   map is wrong points every download at the wrong place.")
        failed.append(index_asset)
        return 0

    line = (f"✅ {index_asset}: HTTP 200 ({len(raw)} B) ·"
            f" schema {info['schema']} · release-tag {info['release-tag']}"
            f" · chipdb-id {info['chipdb-id']} · {info['generated-count']}"
            f" of {info['part-count']} parts built from"
            f" {info['chipdb-count']} chipdb files")
    # These bytes are already here: hashing them is free, and it is the
    # one asset whose SHA256SUMS line nothing else can vouch for.
    if covers_everything:
        published = sums.get(index_asset)
        digest = hashlib.sha256(raw).hexdigest()
        if published is None:
            print(f"❌ {index_asset}: published but MISSING from SHA256SUMS")
            failed.append(index_asset)
            return 0
        if published != digest:
            print(f"❌ {index_asset}: sha256 {digest[:12]}… != SHA256SUMS "
                  f"{published[:12]}…")
            print("   the published index is not the one SHA256SUMS records")
            failed.append(index_asset)
            return 0
        line += " · sha256 == SHA256SUMS"
    print(line)

    # One request per FILE, not per part: the four speed grades of a base
    # part name the same asset, and asking for it four times would be ~200
    # downloads (~3 GB with --full) for the 15 files a release publishes.
    by_asset = {}
    for part, entry in sorted(generated.items()):
        by_asset.setdefault(entry["asset"], (entry, []))[1].append(part)
    for asset, (entry, parts) in sorted(by_asset.items()):
        check_chipdb_asset(asset, entry, parts)
    return len(by_asset)


checked_chipdb = check_chipdb_release()

# The other direction: a manifest line for something this release does not
# describe -- a leftover from an earlier run, or an asset the index forgot.
# Only meaningful when the whole release was walked (no --platform filter,
# and an index this gate could read).
if covers_everything and checked_chipdb and len(platforms) == 3:
    extra = sorted(set(sums) - accounted)
    if extra:
        print(f"❌ SHA256SUMS lists {len(extra)} asset(s) nothing in this "
              f"release describes: {', '.join(extra)}")
        failed.extend(extra)

if failed:
    print(f"\nasset-check: FAIL ({len(failed)}: {', '.join(failed)})")
    sys.exit(1)
tail = (f" and for the {checked_chipdb} chipdb assets of this release"
        if checked_chipdb else "")
if checked_chipdb and covers_everything:
    tail += f"; SHA256SUMS ({len(sums)} entries) agrees with the index"
print(f"\nasset-check: OK — apio's URL rule resolves for every platform{tail}")
PYEOF
