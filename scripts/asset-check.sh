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
# Schema 8 (apio#1070) publishes six assets: the three platform tarballs,
# SHA256SUMS, XILINX-PARTS-INDEX.json and BUILD-INFO.json. The chipdb files
# travel inside each tarball (chipdb/chipdb-<die>.bin), and the index names
# the file each part uses. There is no apio-xilinx-chipdb-*.bin.tgz asset.
# --full downloads each platform package and checks that the bins inside
# it are exactly the files the index names, with the index's chipdb-id.
# A release whose index is not the one apio reads today -- absent under
# every name it has been published with, or an older schema -- predates
# this contract and is reported as legacy, not failed: it is not what
# apio installs from.
#
# SHA256SUMS covers every asset since apio#990 (it used to list only the
# three packages). A schema 8 release's manifest lists the six assets
# above and nothing else.
#
# BUILD-INFO.json is published alongside them since apio#1009: the identity
# of this build -- toolchain revisions, oss-cad-suite tag, chipdb identity,
# the commit and the run -- readable without downloading a 100 MB package,
# the way apio's own releases publish theirs. It must describe THIS release;
# a release without one predates the convention and is legacy, not failed.
#
# Usage:
#   scripts/asset-check.sh <tag>                     # existence + SHA256SUMS
#                                                    # + parts index
#   scripts/asset-check.sh <tag> --expect-dir DIR    # local tarballs must match
#                                                    # the published SHA256SUMS
#   scripts/asset-check.sh <tag> --full              # download each platform
#                                                    # package and check the
#                                                    # chipdb files inside it
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
        -h|--help) sed -n '3,48p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) TAG="$1"; shift ;;
    esac
done
[ -n "$TAG" ] || { echo "usage: scripts/asset-check.sh <tag> [--expect-dir DIR] [--full] [--platform p]..." >&2; exit 2; }
[ ${#PLATFORMS[@]} -gt 0 ] || PLATFORMS=(linux-x86-64 darwin-arm64 windows-amd64)

python3 - "$REPO_ROOT" "$TAG" "$EXPECT_DIR" "$FULL" "${PLATFORMS[@]}" <<'PYEOF'
import hashlib, io, json, os, sys, tarfile, time
import urllib.error, urllib.request

repo_root, tag, expect_dir = sys.argv[1], sys.argv[2], sys.argv[3]
full = sys.argv[4] == "1"
platforms = sys.argv[5:]

# The index is validated by the SAME code that writes it (one validator,
# used by L1 on a package and here on a release).
sys.path.insert(0, repo_root)
from pack.parts_index import (INDEX_ASSET, SCHEMA, STAMP_FILE,  # noqa: E402
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
    # this check makes one request per published asset -- six on a schema 8
    # release, the three platform packages with --full. Retried, with a pause; an
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
# apio#990 it listed the three tarballs alone. Anything that is not a
# platform package marks the wider manifest.
covers_everything = any(not name.startswith("apio-openxc7-") for name in sums)
if sums and not covers_everything:
    print("   the platform packages only: published before SHA256SUMS "
          "covered the rest of the release")

# Platform-package bytes kept when --full downloaded them, so the chipdb
# check below does not fetch each tarball a second time.
package_blobs = {}


def read_hashed(source):
    """(sha256 hex, bytes) of a response or an open binary file."""
    digest = hashlib.sha256()
    chunks = []
    for chunk in iter(lambda: source.read(1 << 20), b""):
        digest.update(chunk)
        chunks.append(chunk)
    return digest.hexdigest(), b"".join(chunks)

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
            remote_sha, blob = read_hashed(resp)
        if published is not None and remote_sha != published:
            print(f"❌ {asset}: downloaded sha256 {remote_sha[:12]}… != SHA256SUMS {published[:12]}…")
            failed.append(asset)
            continue
        package_blobs[asset] = blob
        line += f" · sha256(downloaded) {remote_sha[:12]}…" + (" == SHA256SUMS" if published else "")

    print(line)


# ---------------------------------------------------------------------------
# The build info: the one document that says what this build is (apio#1009).
# ---------------------------------------------------------------------------
BUILD_INFO = "BUILD-INFO.json"


def check_build_info():
    """Validate the published build info; True when the release has one.

    It answers "what exactly is this build" without downloading a package,
    which is what apio's crawler reads it for, so the thing that must hold
    is that it describes THIS release: a run crossing midnight UTC, or a
    leftover from an earlier one, would publish another release's identity
    under this tag.

    Absent, it is only a failure when SHA256SUMS names it -- that manifest
    is written from the bytes this same job uploads, so a release that
    lists the document and does not serve it lost it on the way up.
    Without such a line the release simply predates the convention.
    """
    try:
        with request(f"{base}/{BUILD_INFO}") as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        if BUILD_INFO in sums:
            print(f"❌ {BUILD_INFO}: in SHA256SUMS, not in the release")
            print("   the upload lost the document its own manifest describes")
            failed.append(BUILD_INFO)
        else:
            print(f"— {BUILD_INFO}: not published (HTTP 404)")
            print("  legacy release: published before the build info"
                  " travelled as an asset of its own")
        return False
    accounted.add(BUILD_INFO)

    try:
        info = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        print(f"❌ {BUILD_INFO}: not readable as JSON ({error})")
        failed.append(BUILD_INFO)
        return False

    if info.get("release-tag") != tag:
        print(f"❌ {BUILD_INFO}: release-tag {info.get('release-tag')!r}, not "
              f"{tag!r}")
        print("   the identity published under this tag is another"
              " release's")
        failed.append(BUILD_INFO)
        return False

    # Each package it names must be the one apio resolves for that platform
    # from this tag: the same date rule the tarballs above go through,
    # applied to the document that claims to describe them.
    packages = info.get("packages") or {}
    for platform, entry in sorted(packages.items()):
        expected = f"apio-openxc7-{platform}-{date}.tgz"
        if entry.get("file-name") != expected:
            print(f"❌ {BUILD_INFO}: for {platform} it names "
                  f"{entry.get('file-name')!r}, this release ships "
                  f"{expected}")
            failed.append(BUILD_INFO)
            return False

    line = (f"✅ {BUILD_INFO}: HTTP 200 ({len(raw)} B) · release-tag"
            f" {info['release-tag']} · {len(packages)} packages ·"
            f" nextpnr-xilinx {str(info.get('nextpnr-xilinx-revision'))[:12]}"
            f" · oss-cad-suite {info.get('yosys-release-tag')}")
    # Same free hash as the index: the bytes are already here, and nothing
    # else in the release vouches for this document.
    if covers_everything:
        published = sums.get(BUILD_INFO)
        digest = hashlib.sha256(raw).hexdigest()
        if published is None:
            print(f"❌ {BUILD_INFO}: published but MISSING from SHA256SUMS")
            failed.append(BUILD_INFO)
            return False
        if published != digest:
            print(f"❌ {BUILD_INFO}: sha256 {digest[:12]}… != SHA256SUMS "
                  f"{published[:12]}…")
            print("   the published build info is not the one SHA256SUMS"
                  " records")
            failed.append(BUILD_INFO)
            return False
        line += " · sha256 == SHA256SUMS"
    print(line)
    return True


has_build_info = check_build_info()

# ---------------------------------------------------------------------------
# The parts index. The chipdb files it names travel inside each platform
# package; schema 8 publishes no separate chipdb asset.
# ---------------------------------------------------------------------------
def chipdb_members(blob):
    """(set of chipdb/*.bin names, chipdb-id.txt text) inside a package."""
    bins = set()
    stamp = ""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name[2:] if member.name.startswith("./") else member.name
            if name == f"chipdb/{STAMP_FILE}":
                extracted = archive.extractfile(member)
                stamp = extracted.read().decode().strip() if extracted else ""
            elif (name.startswith("chipdb/") and name.endswith(".bin")
                    and name.count("/") == 1):
                bins.add(name.split("/", 1)[1])
    return bins, stamp


def check_package_chipdb(asset, blob, info, described):
    """--full: the bins inside one platform package match the index."""
    try:
        bins, stamp = chipdb_members(blob)
    except tarfile.TarError as error:
        print(f"❌ {asset}: not a tarball ({error})")
        failed.append(asset)
        return
    missing = sorted(described - bins)
    extra = sorted(bins - described)
    if missing or extra:
        print(f"❌ {asset}: chipdb/ does not match the index: "
              f"missing {missing or 'none'}, unexpected {extra or 'none'}")
        failed.append(asset)
        return
    if stamp != info.get("chipdb-id"):
        found = stamp or "absent"
        print(f"❌ {asset}: chipdb/{STAMP_FILE} is {found!r}, "
              f"index chipdb-id is {info.get('chipdb-id')!r}")
        failed.append(asset)
        return
    print(f"✅ {asset}: {len(bins)} chipdb files inside match the index "
          f"(chipdb-id {stamp})")


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
    """Validate the published parts index. True when this schema was read.

    An absent index, or an older schema, is a legacy release: reported,
    not failed. --full then checks the chipdb files inside each platform
    package against that index.
    """
    index_asset, raw = fetch_index()
    if index_asset is None:
        print(f"— {INDEX_ASSET}: not published (HTTP 404)")
        print("  legacy release: no parts index under any of the names apio"
              " has resolved, so the contract this gate checks is not the"
              " one that release was published under")
        return False
    accounted.add(index_asset)

    try:
        info = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        print(f"❌ {index_asset}: not readable as JSON ({error})")
        failed.append(index_asset)
        return False

    # This schema IS the contract: the index written by the same run that
    # builds the packages (pack/parts_index.py, where SCHEMA is a constant,
    # so a current run cannot produce an older one). An older one is a
    # release from before that contract, and what its assets mean is its
    # own gate's business, not this one's. Reported, never failed.
    if info.get("schema") != SCHEMA:
        print(f"— {index_asset}: schema {info.get('schema')!r}, not {SCHEMA}")
        print("  legacy release: an index older than the contract this gate"
              " checks, so its assets are not what apio installs from today")
        return False

    try:
        generated = validate_document(info, expect_tag=tag)
    except ValueError as error:
        print(f"❌ {index_asset}: {error}")
        print("   apio reads this index to find each part's chipdb file: a")
        print("   release whose map is wrong points every build at the")
        print("   wrong file.")
        failed.append(index_asset)
        return False

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

    # The files named by the index live in each platform package. --full
    # already downloaded those tarballs; check them once each, not once
    # per part (every part of a die names the same file).
    if full:
        described = {entry["chipdb"] for entry in generated.values()}
        for platform in platforms:
            asset = f"apio-openxc7-{platform}-{date}.tgz"
            blob = package_blobs.get(asset)
            if blob is None:
                continue
            check_package_chipdb(asset, blob, info, described)
    return True


index_checked = check_chipdb_release()

# The other direction: a manifest line for something this release does not
# describe -- a leftover chipdb asset from an earlier contract, or a name
# the index forgot. Only meaningful when the whole release was walked (no
# --platform filter, and an index this gate could read).
if covers_everything and index_checked and len(platforms) == 3:
    extra = sorted(set(sums) - accounted)
    if extra:
        print(f"❌ SHA256SUMS lists {len(extra)} asset(s) nothing in this "
              f"release describes: {', '.join(extra)}")
        failed.extend(extra)

if failed:
    print(f"\nasset-check: FAIL ({len(failed)}: {', '.join(failed)})")
    sys.exit(1)
tail = ("; chipdb files travel inside the platform packages"
        + (" and match the index" if full else "")
        if index_checked else "")
if has_build_info:
    tail += "; its BUILD-INFO.json names this very tag"
if index_checked and covers_everything:
    tail += f"; SHA256SUMS ({len(sums)} entries) agrees with the index"
print(f"\nasset-check: OK — apio's URL rule resolves for every platform{tail}")
PYEOF
