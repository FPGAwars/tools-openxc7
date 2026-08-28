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
PART = "xc7a35tcpg236"
ASSET = f"apio-xilinx-chipdb-{PART}-{DATE}.bin.tgz"
INDEX = f"apio-xilinx-chipdb-index-{DATE}.json"
BASE = f"https://github.com/{REPO_SLUG}/releases/download/{TAG}"
BIN = b"chipdb bytes"


def _tgz(payload: bytes, arcname: str) -> bytes:
    """A tar.gz carrying one member, like the published assets."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(arcname)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
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


def release(**overrides) -> dict:
    """A healthy on-demand release: three tarballs, SHA256SUMS, one FPGA."""
    tgz = _tgz(BIN, f"{PART}.bin")
    tarballs = {
        f"apio-openxc7-{platform}-{DATE}.tgz": f"{platform} package".encode()
        for platform in ("linux-x86-64", "darwin-arm64", "windows-amd64")
    }
    sums = "".join(
        f"{hashlib.sha256(body).hexdigest()}  {name}\n"
        for name, body in sorted(tarballs.items())
    )
    info = {
        "schema": 3,
        "date": DATE,
        "release-tag": TAG,
        "chipdb-id": "fixture-id",
        "generated-count": 1,
        "available-count": 1,
        "note": "fixture",
        "parts": {
            PART: {
                "family": "artix7",
                "generated": True,
                "asset": ASSET,
                "size": len(BIN),
                "sha256": hashlib.sha256(BIN).hexdigest(),
                "tgz_size": len(tgz),
                "tgz_sha256": hashlib.sha256(tgz).hexdigest(),
            },
        },
    }
    files = {
        **{f"{BASE}/{name}": body for name, body in tarballs.items()},
        f"{BASE}/SHA256SUMS": sums.encode(),
        f"{BASE}/{INDEX}": json.dumps(info).encode(),
        f"{BASE}/{ASSET}": tgz,
    }
    files.update(overrides)
    return {url: body for url, body in files.items() if body is not None}


def run(files, *args, flaky=0) -> tuple:
    """Run the script's python over *files*; return (exit code, output).

    *flaky* makes the first N calls fail the way a dropped connection does.
    """
    source = SCRIPT.read_text().split("<<'PYEOF'", 1)[1].rsplit("PYEOF", 1)[0]
    remaining = [flaky]

    def fake_urlopen(request, timeout=None):
        if remaining[0]:
            remaining[0] -= 1
            raise urllib.error.URLError(TimeoutError("timed out"))
        url = request.full_url
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
        self.assertIn(f"✅ {ASSET}", output)
        self.assertIn("1 chipdb assets", output)

    def test_declared_asset_missing_fails_naming_it(self):
        """The failure the gate exists for: an FPGA nobody can build for."""
        code, output = run(release(**{f"{BASE}/{ASSET}": None}))
        self.assertEqual(code, 1)
        self.assertIn(f"❌ {ASSET}: HTTP 404", output)
        self.assertIn(f"apio WILL 404 for {PART}", output)
        self.assertIn(f"asset-check: FAIL (1: {ASSET})", output)

    def test_truncated_asset_fails(self):
        code, output = run(release(**{f"{BASE}/{ASSET}": b"half an upload"}))
        self.assertEqual(code, 1)
        self.assertIn(f"❌ {ASSET}: 14 bytes published, document says", output)

    def test_document_counts_must_add_up(self):
        files = release()
        info = json.loads(files[f"{BASE}/{INDEX}"])
        info["generated-count"] = 2
        files[f"{BASE}/{INDEX}"] = json.dumps(info).encode()
        code, output = run(files)
        self.assertEqual(code, 1)
        self.assertIn("generated-count 2 != 1 generated entries", output)
        self.assertIn(f"asset-check: FAIL (1: {INDEX})", output)

    def test_document_from_another_release_fails(self):
        """A run crossing midnight UTC would publish yesterday's map."""
        files = release()
        info = json.loads(files[f"{BASE}/{INDEX}"])
        info.update({"date": "20260827", "release-tag": "2026-08-27"})
        files[f"{BASE}/{INDEX}"] = json.dumps(info).encode()
        code, output = run(files)
        self.assertEqual(code, 1)
        self.assertIn("is not the release it was published in", output)

    def test_release_without_a_document_is_legacy_not_a_failure(self):
        code, output = run(release(**{f"{BASE}/{INDEX}": None}))
        self.assertEqual(code, 0, output)
        self.assertIn("legacy release: packages carry the chipdb", output)
        self.assertIn("asset-check: OK", output)

    def test_older_schema_is_legacy_not_a_failure(self):
        """2026-08-20 publishes the apio#900 document; its packages carry
        the chipdb, so its per-FPGA assets are not load-bearing."""
        files = release()
        files[f"{BASE}/{INDEX}"] = json.dumps(
            {"date": DATE, "chipdb_id": "x", "parts": []}).encode()
        code, output = run(files)
        self.assertEqual(code, 0, output)
        self.assertIn("schema None, not 3", output)
        self.assertIn("legacy release", output)

    def test_full_checks_the_hashes_and_the_bin_inside(self):
        files = release()
        # Right size, wrong bytes: only --full can see it.
        payload = _tgz(b"other bytes!", f"{PART}.bin")
        info = json.loads(files[f"{BASE}/{INDEX}"])
        info["parts"][PART]["tgz_size"] = len(payload)
        files[f"{BASE}/{INDEX}"] = json.dumps(info).encode()
        files[f"{BASE}/{ASSET}"] = payload
        code, output = run(files)
        self.assertEqual(code, 0, output)      # size-only pass
        code, output = run(files, "", "1")     # --full
        self.assertEqual(code, 1)
        self.assertIn("!= document tgz_sha256", output)

    def test_full_rejects_an_asset_without_the_bin_at_its_root(self):
        files = release()
        payload = _tgz(BIN, f"chipdb/{PART}.bin")
        info = json.loads(files[f"{BASE}/{INDEX}"])
        info["parts"][PART].update(
            tgz_size=len(payload), tgz_sha256=hashlib.sha256(payload).hexdigest())
        files[f"{BASE}/{INDEX}"] = json.dumps(info).encode()
        files[f"{BASE}/{ASSET}"] = payload
        code, output = run(files, "", "1")
        self.assertEqual(code, 1)
        self.assertIn(f"does not carry {PART}.bin at its root", output)

    def test_a_dropped_connection_is_retried_not_reported_as_missing(self):
        """A flaky link must not read as 'the release is broken' — and on
        an on-demand release this makes twenty requests, not four."""
        code, output = run(release(), flaky=2)
        self.assertEqual(code, 0, output)
        self.assertIn("retrying (1/2)", output)
        self.assertIn("asset-check: OK", output)

    def test_a_link_that_stays_down_still_fails(self):
        with self.assertRaises(urllib.error.URLError):
            run(release(), flaky=99)

    def test_missing_platform_tarball_still_fails(self):
        gone = f"apio-openxc7-darwin-arm64-{DATE}.tgz"
        code, output = run(release(**{f"{BASE}/{gone}": None}))
        self.assertEqual(code, 1)
        self.assertIn("apio WILL 404 on darwin-arm64", output)


if __name__ == "__main__":
    unittest.main()
