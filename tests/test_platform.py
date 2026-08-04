"""Tests for pack.platform.plat_token (mocking platform.system/machine)."""

import unittest
from unittest import mock

from pack.platform import plat_token


class TestPlatToken(unittest.TestCase):

    def check(self, sysname: str, machine: str, expected: str):
        with mock.patch("platform.system", return_value=sysname), \
             mock.patch("platform.machine", return_value=machine):
            self.assertEqual(plat_token(), expected)

    # -- Linux: x86_64/amd64 normalize to the historic 'x86-64' token
    def test_linux_x86_64(self):
        self.check("Linux", "x86_64", "linux-x86-64")

    def test_linux_amd64(self):
        self.check("Linux", "amd64", "linux-x86-64")

    def test_linux_aarch64(self):
        self.check("Linux", "aarch64", "linux-aarch64")

    def test_linux_arm64(self):
        self.check("Linux", "arm64", "linux-aarch64")

    def test_linux_other_machine_passthrough(self):
        self.check("Linux", "riscv64", "linux-riscv64")

    # -- Darwin: arm64/aarch64 normalize to 'arm64'
    def test_darwin_arm64(self):
        self.check("Darwin", "arm64", "darwin-arm64")

    def test_darwin_aarch64(self):
        self.check("Darwin", "aarch64", "darwin-arm64")

    def test_darwin_x86_64(self):
        self.check("Darwin", "x86_64", "darwin-x86-64")

    def test_unsupported_platform_exits(self):
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("platform.machine", return_value="AMD64"):
            with self.assertRaises(SystemExit):
                plat_token()


if __name__ == "__main__":
    unittest.main()
