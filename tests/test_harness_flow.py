"""Tests for the regression harness flow (regress/harness/flow.py).

The steps are replaced by a recorder that writes what each tool would, so
the command lines are checked without a package or a toolchain.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "regress" / "harness"))

import flow  # noqa: E402


class _FakePackage:
    schema = 7
    env_extra: dict = {}

    def __init__(self, root: Path):
        self.root = root
        self.db = root / "share/nextpnr/external/prjxray-db"

    def cmd(self, name):
        return [str(self.root / "bin" / name)]

    def python_cmd(self, script):
        return ["python3", str(script)]

    def device(self, part, strict=True):
        return f"{part}-1"

    def chipdb(self, part):
        return self.root / "chipdb" / "chipdb-xc7a50t.bin"


def _spec(directory: Path):
    (directory / "top.xdc").write_text("")
    return SimpleNamespace(
        constraints="top.xdc", xdc_extra=[], directory=directory,
        parameters={}, top="top", synth_opts="", sources=[],
        flow="bitstream", timeout=60, router="router2", nextpnr_args=[],
    )


class XcFrames2BitCommand(unittest.TestCase):
    def test_the_frames_file_is_passed_relative_to_the_workdir(self):
        """xc7frames2bit copies --frm_file into the .bit header, so the
        size of the bitstream must not depend on where the suite runs."""
        commands = {}

        def step(session, name, cmd, stdout_to=None, env_extra=None):
            commands[name] = (cmd, session.workdir)
            work = session.workdir
            if name == "yosys":
                (work / "netlist.json").write_text(json.dumps({"modules": {}}))
            elif name == "nextpnr-xilinx":
                (work / "report.json").write_text(
                    json.dumps({"fmax": {}, "utilization": {}}))
            elif name == "fasm2frames":
                stdout_to.write_text("frames\n")
            elif name == "xc7frames2bit":
                (work / "design.bit").write_bytes(b"bit")
            return 0.0

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            workdir = root / "a-long-work-root" / "test" / "xc7a35tcpg236"
            with mock.patch.object(flow._Session, "step", step):
                result = flow.run(_spec(root), _FakePackage(root / "pkg"),
                                  "xc7a35tcpg236", workdir, REPO)

        self.assertTrue(result.ok, result.error)
        cmd, cwd = commands["xc7frames2bit"]
        frm = cmd[cmd.index("--frm_file") + 1]
        self.assertEqual(frm, "design.frames")
        self.assertEqual(cwd, workdir)


if __name__ == "__main__":
    unittest.main()
