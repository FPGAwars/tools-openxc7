"""The package under test: an extracted openXC7 tree and how to invoke it.

Tools are taken from the package itself (its `bin/` wrappers), the same ones a
user gets after `source start`, so the suite measures the artefact we ship and
not whatever happens to be on PATH.
"""

from __future__ import annotations

import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Package:
    root: Path
    platform: str
    _tmp: object = field(default=None, repr=False)

    @classmethod
    def open(cls, path: Path) -> "Package":
        tmp = None
        if path.is_dir():
            root = path.resolve()
        else:
            tmp = tempfile.TemporaryDirectory(prefix="openxc7-regress-")
            with tarfile.open(path) as tar:
                tar.extractall(tmp.name)
            root = Path(tmp.name)

        if (root / "bin" / "nextpnr-xilinx.exe").exists():
            raise SystemExit(
                "this is a windows package: running the suite under wine is not wired yet"
            )
        if not (root / "libexec" / "nextpnr-xilinx").exists():
            raise SystemExit(f"unrecognised package layout at {root}")

        host = subprocess.run(["uname", "-s"], capture_output=True, text=True).stdout.strip()
        platform = {"Darwin": "darwin-arm64", "Linux": "linux-x86-64"}.get(host)
        if platform is None:
            raise SystemExit(f"unsupported host: {host}")
        return cls(root=root, platform=platform, _tmp=tmp)

    def tool(self, name: str) -> str:
        candidate = self.root / "bin" / name
        return str(candidate) if candidate.exists() else name

    @property
    def db(self) -> Path:
        return self.root / "share" / "nextpnr" / "external" / "prjxray-db"

    def chipdb(self, part: str) -> Path:
        return self.root / "chipdb" / f"{part}.bin"

    def device(self, part: str) -> str:
        """The part with its speedgrade, e.g. xc7a35tcpg236 -> xc7a35tcpg236-1."""
        matches = sorted(d.name for d in (self.db / "artix7").glob(f"{part}-*") if d.is_dir())
        if not matches:
            raise SystemExit(f"part {part} is not in the packaged prjxray-db")
        return matches[0]

    def versions(self) -> dict:
        def first_line(cmd: list[str]) -> str:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                return (proc.stdout or proc.stderr).strip().splitlines()[0]
            except (OSError, IndexError):
                return "unknown"

        return {
            "yosys": first_line(["yosys", "-V"]),
            "nextpnr": first_line([self.tool("nextpnr-xilinx"), "--version"]),
        }
