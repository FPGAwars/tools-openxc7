"""Tests for scripts/asset-check.sh, the release gate, without a network.

The script is bash around one embedded python program; the tests run THAT
program (extracted from the file, so a change to it is a change to what is
tested) against a fake release served by a stubbed urlopen.
"""

import hashlib
import io
import json
import sys
import tarfile
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "asset-check.sh"
REPO_SLUG = "fixture/tools-openxc7"
TAG = "2026-08-28"
DATE = "20260828"
BASE_PART = "xc7a35tcpg236"
PARTS = (f"{BASE_PART}-1", f"{BASE_PART}-2L")   # one chipdb file, two parts
# xc7a35t is the xc7a50t die: schema 8 names that die's file.
CHIPDB = "chipdb-xc7a50t.bin"
STAMP = "fixture-id"
# A name schema 7 published and schema 8 must not.
ASSET = f"apio-xilinx-chipdb-xc7a50t-{DATE}.bin.tgz"
INDEX = "XILINX-PARTS-INDEX.json"        # since the apio#1002 rename
BUILD_INFO = "BUILD-INFO.json"           # the release-level one, apio#1009
PREVIOUS_INDEX = "PARTS-INDEX.json"      # apio#990, up to the rename
LEGACY_INDEX = f"apio-xilinx-parts-index-{DATE}.json"   # up to 2026-08-31
BASE = f"https://github.com/{REPO_SLUG}/releases/download/{TAG}"
BIN = b"chipdb bytes"
# The document of the 2026-09-15 release as published: the last schema 5.
PUBLISHED_SCHEMA_5 = REPO / "tests" / "data" / "XILINX-PARTS-INDEX-2026-09-15.json"


def _tgz(payload: bytes, arcname: str) -> bytes:
    """A tar.gz carrying one member."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(arcname)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _package(payload: bytes = BIN, stamp: str = STAMP,
             extra=()) -> bytes:
    """A platform package carrying chipdb/<file> and chipdb-id.txt."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        members = [(f"chipdb/{CHIPDB}", payload),
                   ("chipdb/chipdb-id.txt", (stamp + "\n").encode())]
        members.extend(extra)
        for name, data in members:
            if data is None:
                continue
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeResponse(io.BytesIO):
    """Enough of an http response for the script: status, headers, read()."""

    def __init__(self, payload: bytes):
        super().__init__(payload)
        self.status = 200
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def resum(files: dict, promised=None) -> dict:
    """Rewrite SHA256SUMS over whatever the release publishes right now.

    The real one is written by the publishing job from the bytes it
    uploads, so it always describes them; a test that changes an asset
    calls this to keep that true and break only the thing under test.

    *promised* gives the bytes the manifest was written from for an asset
    whose published bytes differ -- an upload that landed something else
    after both documents were written, which is exactly what no amount of
    cross-checking metadata can see and --full can.
    """
    published = {url.rsplit("/", 1)[1]: body for url, body in files.items()
                 if not url.endswith("/SHA256SUMS")}
    published.update(promised or {})
    files[f"{BASE}/SHA256SUMS"] = "".join(
        f"{hashlib.sha256(body).hexdigest()}  {name}\n"
        for name, body in sorted(published.items())).encode()
    return files


def release(**overrides) -> dict:
    """A healthy schema 8 release: three packages, the index, BUILD-INFO.

    Six assets once SHA256SUMS is added. No chipdb release asset: the bin
    travels inside each platform package.
    """
    tarballs = {
        f"apio-openxc7-{platform}-{DATE}.tgz": _package()
        for platform in ("linux-x86-64", "darwin-arm64", "windows-amd64")
    }
    built = {"generated": True, "chipdb": CHIPDB}
    info = {
        "schema": 8,
        "date": DATE,
        "release-tag": TAG,
        "chipdb-id": "fixture-id",
        "part-count": len(PARTS),
        "generated-count": len(PARTS),
        "chipdb-count": 1,
        "base-part-count": 1,
        "note": "fixture",
        "parts": {
            part: {"family": "artix7", "base-part": BASE_PART,
                   "speed": part.rsplit("-", 1)[1], **built}
            for part in PARTS
        },
    }
    build_info = {
        "package-name": "openxc7",
        "release-tag": TAG,
        "yosys-release-tag": "2026-03-24",
        "nextpnr-xilinx-revision": "68aeeb39f92e39bfb239c7e4a44dd93451fc1889",
        "chipdb-id": "fixture-id",
        "commit": "3931811fdb26d2eaf484f2eb63d7db976e43316f",
        "packages": {
            platform: {"file-name": f"apio-openxc7-{platform}-{DATE}.tgz",
                       "build-time": "2026-08-28 09:00:00 UTC"}
            for platform in ("linux-x86-64", "darwin-arm64",
                             "windows-amd64")},
    }
    files = {
        **{f"{BASE}/{name}": body for name, body in tarballs.items()},
        f"{BASE}/{BUILD_INFO}": json.dumps(build_info).encode(),
        f"{BASE}/{INDEX}": json.dumps(info).encode(),
    }
    files.update(overrides)
    files = {url: body for url, body in files.items() if body is not None}
    # SHA256SUMS covers every asset of the release (apio#990), so it is
    # computed from what this release actually publishes.
    return resum(files)


def run(files, *args, flaky=0, calls=None) -> tuple:
    """Run the script's python over *files*; return (exit code, output).

    *flaky* makes the first N calls fail the way a dropped connection does;
    *calls*, if given, collects every URL the script actually requests.
    """
    source = SCRIPT.read_text().split("<<'PYEOF'", 1)[1].rsplit("PYEOF", 1)[0]
    remaining = [flaky]

    def fake_urlopen(request, timeout=None):
        if remaining[0]:
            remaining[0] -= 1
            raise urllib.error.URLError(TimeoutError("timed out"))
        url = request.full_url
        if calls is not None:
            calls.append(url)
        if url not in files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return FakeResponse(files[url])

    argv = ["-", str(REPO), TAG, "", "0",
            "linux-x86-64", "darwin-arm64", "windows-amd64"]
    for index, value in enumerate(args):
        argv[3 + index] = value
    output = io.StringIO()
    code = 0
    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(time, "sleep", lambda seconds: None), \
            mock.patch.dict("os.environ", {"ASSET_CHECK_REPO": REPO_SLUG}), \
            mock.patch.object(sys, "argv", argv), redirect_stdout(output):
        try:
            exec(compile(source, str(SCRIPT), "exec"), {"__name__": "__main__"})
        except SystemExit as exit_code:
            code = exit_code.code or 0
    return code, output.getvalue()


class AssetCheckTests(unittest.TestCase):
    def test_healthy_release_passes(self):
        code, output = run(release())
        self.assertEqual(code, 0, output)
        self.assertIn("asset-check: OK", output)
        self.assertIn(f"✅ {INDEX}", output)
        self.assertIn("schema 8", output)
        self.assertIn("travel inside the platform packages", output)
        self.assertNotIn(ASSET, output)
        self.assertNotIn("chipdb assets", output)

    def test_one_request_for_the_index_not_per_part(self):
        """Two parts share a chipdb file: the index is fetched once.

        Schema 8 does not fetch a chipdb asset at all.
        """
        calls = []
        code, output = run(release(), calls=calls)
        self.assertEqual(code, 0, output)
        self.assertEqual(calls.count(f"{BASE}/{INDEX}"), 1)
        self.assertEqual([url for url in calls if url.endswith(".bin.tgz")], [])

    def test_full_names_a_missing_bin(self):
        """--full opens each package. A bin the index names and the
        package lacks is the failure, and it is named."""
        linux = f"apio-openxc7-linux-x86-64-{DATE}.tgz"
        files = release(**{f"{BASE}/{linux}": _package(payload=None)})
        code, output = run(resum(files))
        self.assertEqual(code, 0, output)
        code, output = run(resum(files), "", "1")
        self.assertEqual(code, 1)
        self.assertIn(f"missing ['{CHIPDB}']", output)
        self.assertIn(linux, output)

    def test_full_names_an_extra_bin(self):
        linux = f"apio-openxc7-linux-x86-64-{DATE}.tgz"
        files = release(**{f"{BASE}/{linux}": _package(
            extra=[("chipdb/extra.bin", b"no such part")])})
        code, output = run(resum(files), "", "1")
        self.assertEqual(code, 1)
        self.assertIn("unexpected ['extra.bin']", output)

    def test_document_counts_must_add_up(self):
        files = release()
        info = json.loads(files[f"{BASE}/{INDEX}"])
        info["generated-count"] = 3
        files[f"{BASE}/{INDEX}"] = json.dumps(info).encode()
        code, output = run(resum(files))
        self.assertEqual(code, 1)
        self.assertIn(f"generated-count 3 != {len(PARTS)}", output)
        self.assertIn(f"asset-check: FAIL (1: {INDEX})", output)

    def test_document_from_another_release_fails(self):
        """A run crossing midnight UTC would publish yesterday's map."""
        files = release()
        info = json.loads(files[f"{BASE}/{INDEX}"])
        info.update({"date": "20260827", "release-tag": "2026-08-27"})
        files[f"{BASE}/{INDEX}"] = json.dumps(info).encode()
        code, output = run(resum(files))
        self.assertEqual(code, 1)
        self.assertIn("is not the release it was published in", output)

    def test_release_without_an_index_is_legacy_not_a_failure(self):
        """No published name resolves: a release from before the contract."""
        code, output = run(release(**{f"{BASE}/{INDEX}": None}))
        self.assertEqual(code, 0, output)
        self.assertIn("not published (HTTP 404)", output)
        self.assertIn("legacy release: no parts index under any of the names",
                      output)
        self.assertIn("asset-check: OK", output)

    def test_the_previous_index_name_is_still_read(self):
        """Releases between apio#990 and the apio#1002 rename published
        the index as PARTS-INDEX.json.

        They are still installed from and still promotable, and apio's
        loader accepts that name, so calling them legacy would drop
        their chipdb files from the gate that promotes them.
        """
        files = release()
        files[f"{BASE}/{PREVIOUS_INDEX}"] = files.pop(f"{BASE}/{INDEX}")
        code, output = run(resum(files))
        self.assertEqual(code, 0, output)
        self.assertIn(f"✅ {PREVIOUS_INDEX}", output)
        self.assertIn("travel inside the platform packages", output)
        self.assertNotIn(ASSET, output)

    def test_the_legacy_dated_index_name_is_still_read(self):
        """Every release up to 2026-08-31 published the index dated.

        The oldest name this gate resolves: those releases predate the
        fixed-name convention (apio#990) and are still installed from.
        """
        files = release()
        files[f"{BASE}/{LEGACY_INDEX}"] = files.pop(f"{BASE}/{INDEX}")
        code, output = run(resum(files))
        self.assertEqual(code, 0, output)
        self.assertIn(f"✅ {LEGACY_INDEX}", output)
        self.assertIn("travel inside the platform packages", output)
        self.assertNotIn(ASSET, output)

    def test_older_schema_is_legacy_not_a_failure(self):
        """An index from before this contract is not this gate's business.

        Schema 4 is a real one: the releases published with the previous
        field names (size/tgz_size, renamed in apio#947).
        """
        files = release()
        files[f"{BASE}/{INDEX}"] = json.dumps(
            {"schema": 4, "date": DATE, "chipdb-id": "x",
             "parts": {}}).encode()
        code, output = run(files)
        self.assertEqual(code, 0, output)
        self.assertIn("schema 4, not 8", output)
        self.assertIn("legacy release", output)

    def test_the_last_schema_5_index_is_legacy_not_a_failure(self):
        """The index the 2026-09-15 release published, byte for byte.

        Schema 8 is what this gate checks; a release published under
        schema 5 is what apio 1.6.x installs from, and it is not this
        gate's contract any more.
        """
        files = release()
        files[f"{BASE}/{INDEX}"] = PUBLISHED_SCHEMA_5.read_bytes()
        code, output = run(resum(files))
        self.assertEqual(code, 0, output)
        self.assertIn(f"— {INDEX}: schema 5, not 8", output)
        self.assertIn("legacy release", output)
        self.assertIn("asset-check: OK", output)

    def test_a_schema_6_index_is_legacy_not_a_failure(self):
        """Schema 6 is an older engine's index. This gate checks schema 8,
        so a schema 6 release is legacy, not a failed one."""
        files = release()
        info = json.loads(files[f"{BASE}/{INDEX}"])
        info["schema"] = 6
        files[f"{BASE}/{INDEX}"] = json.dumps(info).encode()
        code, output = run(files)
        self.assertEqual(code, 0, output)
        self.assertIn(f"— {INDEX}: schema 6, not 8", output)
        self.assertIn("legacy release", output)
        self.assertNotIn("❌", output)

    def test_a_schema_7_index_is_legacy_not_a_failure(self):
        """Schema 7 is the previous on-demand contract. A release published
        under it (2026-09-25) is what apio main installs until it moves,
        and this gate reports it legacy rather than failing it."""
        files = release()
        info = json.loads(files[f"{BASE}/{INDEX}"])
        info["schema"] = 7
        files[f"{BASE}/{INDEX}"] = json.dumps(info).encode()
        code, output = run(files)
        self.assertEqual(code, 0, output)
        self.assertIn(f"— {INDEX}: schema 7, not 8", output)
        self.assertIn("legacy release", output)
        self.assertIn("asset-check: OK", output)
        self.assertNotIn("❌", output)

    def test_full_checks_the_downloaded_package_against_sha256sums(self):
        """The published bytes differ from the manifest. HEAD cannot see
        it; --full can."""
        linux = f"apio-openxc7-linux-x86-64-{DATE}.tgz"
        files = release()
        original = files[f"{BASE}/{linux}"]
        files[f"{BASE}/{linux}"] = _package(payload=b"other bytes!")
        files = resum(files, promised={linux: original})
        code, output = run(files)
        self.assertEqual(code, 0, output)
        code, output = run(files, "", "1")
        self.assertEqual(code, 1)
        self.assertIn("!= SHA256SUMS", output)

    def test_full_rejects_a_stamp_that_is_not_the_index(self):
        linux = f"apio-openxc7-linux-x86-64-{DATE}.tgz"
        files = release(**{f"{BASE}/{linux}": _package(stamp="other-toolchain")})
        code, output = run(resum(files), "", "1")
        self.assertEqual(code, 1)
        self.assertIn("chipdb-id.txt", output)
        self.assertIn("other-toolchain", output)

    def test_full_accepts_the_bins_inside_every_package(self):
        code, output = run(release(), "", "1")
        self.assertEqual(code, 0, output)
        self.assertIn("and match the index", output)
        self.assertEqual(output.count("chipdb files inside match the index"), 3)

    def test_a_dropped_connection_is_retried_not_reported_as_missing(self):
        """A flaky link must not read as 'the release is broken'."""
        code, output = run(release(), flaky=2)
        self.assertEqual(code, 0, output)
        self.assertIn("retrying (1/2)", output)
        self.assertIn("asset-check: OK", output)

    def test_a_link_that_stays_down_still_fails(self):
        with self.assertRaises(urllib.error.URLError):
            run(release(), flaky=99)

    def test_the_index_missing_from_sha256sums_fails(self):
        """SHA256SUMS covers the whole release since apio#990: an index
        it does not list is a manifest that stopped describing the
        release it travels with."""
        files = release()
        lines = files[f"{BASE}/SHA256SUMS"].decode().splitlines(True)
        files[f"{BASE}/SHA256SUMS"] = "".join(
            line for line in lines if INDEX not in line).encode()
        code, output = run(files)
        self.assertEqual(code, 1)
        self.assertIn(f"❌ {INDEX}: published but MISSING from SHA256SUMS",
                      output)

    def test_a_tampered_index_line_fails(self):
        """The index is the one asset whose SHA256SUMS line nothing else
        can vouch for -- and its bytes are downloaded anyway."""
        files = release()
        digest = hashlib.sha256(files[f"{BASE}/{INDEX}"]).hexdigest()
        files[f"{BASE}/SHA256SUMS"] = files[f"{BASE}/SHA256SUMS"].decode(
            ).replace(digest, "1" * 64).encode()
        code, output = run(files)
        self.assertEqual(code, 1)
        self.assertIn(f"❌ {INDEX}: sha256", output)
        self.assertIn("not the one SHA256SUMS records", output)

    def test_a_manifest_line_for_nothing_in_the_release_fails(self):
        """The leftover an incremental publish would produce: a name in
        SHA256SUMS that neither the packages nor the index describe."""
        files = release()
        files[f"{BASE}/SHA256SUMS"] += (
            f"{'2' * 64}  apio-xilinx-chipdb-xc7a200tfbg484-{DATE}.bin.tgz\n"
        ).encode()
        code, output = run(files)
        self.assertEqual(code, 1)
        self.assertIn("SHA256SUMS lists 1 asset(s) nothing in this release "
                      "describes", output)

    def test_a_manifest_of_only_the_packages_is_accepted(self):
        """How every release up to 2026-08-31 published it. Requiring the
        index and the build info there would fail a release that was
        complete when it was made."""
        files = release()
        lines = files[f"{BASE}/SHA256SUMS"].decode().splitlines(True)
        files[f"{BASE}/SHA256SUMS"] = "".join(
            line for line in lines if "apio-openxc7-" in line).encode()
        code, output = run(files)
        self.assertEqual(code, 0, output)
        self.assertIn("the platform packages only", output)
        self.assertIn("asset-check: OK", output)

    def test_the_build_info_of_the_release_is_checked(self):
        """apio's crawler reads it to learn what this build is (apio#1009);
        the gate reads it to confirm it is THIS build."""
        code, output = run(release())
        self.assertEqual(code, 0, output)
        self.assertIn(f"✅ {BUILD_INFO}", output)
        self.assertIn("3 packages", output)
        self.assertIn("sha256 == SHA256SUMS", output)
        self.assertIn("names this very tag", output)

    def test_a_build_info_the_manifest_names_but_the_release_lacks_fails(self):
        """The upload that lost one file: SHA256SUMS is written from the
        bytes the same job uploads, so a line without an asset is a
        release that did not finish going up."""
        files = release()
        promised = files.pop(f"{BASE}/{BUILD_INFO}")
        code, output = run(resum(files, promised={BUILD_INFO: promised}))
        self.assertEqual(code, 1)
        self.assertIn(f"❌ {BUILD_INFO}: in SHA256SUMS, not in the release",
                      output)

    def test_a_release_without_a_build_info_is_legacy_not_a_failure(self):
        """Releases before apio#1009 carried it inside the packages only,
        and they are still installed from and still promotable."""
        files = release(**{f"{BASE}/{BUILD_INFO}": None})
        lines = files[f"{BASE}/SHA256SUMS"].decode().splitlines(True)
        files[f"{BASE}/SHA256SUMS"] = "".join(
            line for line in lines if BUILD_INFO not in line).encode()
        code, output = run(files)
        self.assertEqual(code, 0, output)
        self.assertIn("legacy release: published before the build info",
                      output)
        self.assertIn("asset-check: OK", output)

    def test_a_build_info_from_another_release_fails(self):
        """The same midnight-UTC failure the index is guarded against."""
        files = release()
        info = json.loads(files[f"{BASE}/{BUILD_INFO}"])
        info["release-tag"] = "2026-08-27"
        files[f"{BASE}/{BUILD_INFO}"] = json.dumps(info).encode()
        code, output = run(resum(files))
        self.assertEqual(code, 1)
        self.assertIn("release-tag '2026-08-27'", output)
        self.assertIn("another release's", output)

    def test_a_build_info_naming_another_releases_package_fails(self):
        files = release()
        info = json.loads(files[f"{BASE}/{BUILD_INFO}"])
        info["packages"]["darwin-arm64"]["file-name"] = (
            "apio-openxc7-darwin-arm64-20260827.tgz")
        files[f"{BASE}/{BUILD_INFO}"] = json.dumps(info).encode()
        code, output = run(resum(files))
        self.assertEqual(code, 1)
        self.assertIn("for darwin-arm64 it names", output)
        self.assertIn(f"this release ships apio-openxc7-darwin-arm64-{DATE}",
                      output)

    def test_a_tampered_build_info_line_fails(self):
        files = release()
        digest = hashlib.sha256(files[f"{BASE}/{BUILD_INFO}"]).hexdigest()
        files[f"{BASE}/SHA256SUMS"] = files[f"{BASE}/SHA256SUMS"].decode(
            ).replace(digest, "3" * 64).encode()
        code, output = run(files)
        self.assertEqual(code, 1)
        self.assertIn(f"❌ {BUILD_INFO}: sha256", output)
        self.assertIn("not the one SHA256SUMS records", output)

    def test_a_build_info_that_is_not_json_fails(self):
        files = release(**{f"{BASE}/{BUILD_INFO}": b"<html>404</html>"})
        code, output = run(resum(files))
        self.assertEqual(code, 1)
        self.assertIn(f"❌ {BUILD_INFO}: not readable as JSON", output)

    def test_missing_platform_tarball_still_fails(self):
        gone = f"apio-openxc7-darwin-arm64-{DATE}.tgz"
        code, output = run(release(**{f"{BASE}/{gone}": None}))
        self.assertEqual(code, 1)
        self.assertIn("apio WILL 404 on darwin-arm64", output)


if __name__ == "__main__":
    unittest.main()
