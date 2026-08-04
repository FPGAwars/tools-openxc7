"""The package under test: an extracted openXC7 tree and how to invoke it.

Tools are taken from the package itself (its `bin/` wrappers), the same ones a
user gets after `source start`, so the suite measures the artefact we ship and
not whatever happens to be on PATH.
"""

from __future__ import annotations

import subprocess
import tarfile
import tempfile
import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from pack.families import family_of


def _windows_python() -> str:
    """Prefix of a mingw python usable under wine ($E2E_WINPY, or the store)."""
    desde_env = os.environ.get("E2E_WINPY", "")
    if desde_env:
        return desde_env
    candidatos = [p for p in glob.glob("/nix/store/*-python3-x86_64-w64-mingw32-*")
                  if not p.endswith(".drv") and Path(p, "bin/python3.exe").exists()]
    return sorted(candidatos)[-1] if candidatos else ""


@dataclass
class Package:
    root: Path
    platform: str
    wine: bool = False
    winpy: str = ""
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
            return cls(root=root, platform="windows-amd64", wine=True,
                       winpy=_windows_python(), _tmp=tmp)
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

    def cmd(self, name: str) -> list:
        """How to invoke one of the package's tools, as a command list.

        Windows packages run their .exe under wine, so callers must not
        assume a single executable path — hence a list rather than a string.
        """
        if not self.wine:
            return [self.tool(name)]
        return ["wine64", str(self.root / "bin" / f"{name}.exe")]

    def python_cmd(self, script: Path) -> list:
        """How to run one of the packaged python tools.

        On Windows apio runs them with oss-cad-suite's WINDOWS python, not a
        POSIX one, and that is where POSIX-isms (fcntl, /dev/stdout) surface.
        Validating with the host python instead would miss exactly the bugs
        this platform has produced, so the mingw interpreter is required.
        """
        if not self.wine:
            return [self.tool(script.name)]
        if not self.winpy:
            raise SystemExit(
                "no Windows python found: set E2E_WINPY to a mingw python prefix "
                "(a host python would not exercise the path apio actually uses)"
            )
        return ["wine64", f"{self.winpy}/bin/python3.exe", str(script)]

    @property
    def env_extra(self) -> dict:
        if not self.wine:
            return {}
        entorno = {"PYTHONPATH": str(self.root / "lib/python3.12/site-packages"),
                   "WINEDEBUG": "-all"}
        # wine refuses to create its configuration under a directory it does
        # not own (a shared /tmp, typically), so give it one in $HOME unless
        # the caller already chose a prefix.
        if not os.environ.get("WINEPREFIX"):
            entorno["WINEPREFIX"] = str(Path.home() / ".wine-openxc7-regress")
        return entorno

    @property
    def db(self) -> Path:
        return self.root / "share" / "nextpnr" / "external" / "prjxray-db"

    def chipdb(self, part: str) -> Path:
        return self.root / "chipdb" / f"{part}.bin"

    def device(self, part: str) -> str:
        """The part with its speedgrade, e.g. xc7a35tcpg236 -> xc7a35tcpg236-1."""
        matches = sorted(d.name for d in (self.db / family_of(part)).glob(f"{part}-*") if d.is_dir())
        if not matches:
            raise SystemExit(f"part {part} is not in the packaged prjxray-db")
        return matches[0]

    def versions(self) -> dict:
        # wine prattles on stderr ("0084:fixme:hid:..."), and whatever lands
        # here is recorded in the baseline and compared against later runs —
        # so noise would produce spurious "different tool versions" warnings.
        ruido = re.compile(r"^[0-9a-f]{4,}:(fixme|err|warn|trace):")

        def first_line(cmd: list) -> str:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      stdin=subprocess.DEVNULL,
                                      env={**os.environ, **self.env_extra})
                lineas = [ln.strip() for ln in
                          ((proc.stdout or "") + (proc.stderr or "")).splitlines()
                          if ln.strip() and not ruido.match(ln.strip())]
                return lineas[0] if lineas else "unknown"
            except (OSError, IndexError):
                return "unknown"

        return {
            "yosys": first_line(["yosys", "-V"]),
            "nextpnr": first_line(self.cmd("nextpnr-xilinx") + ["--version"]),
        }
