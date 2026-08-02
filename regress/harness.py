#!/usr/bin/env python3
"""Regression runner: build every design against a package and compare the
result with the recorded baseline for this platform.

Invoked through scripts/regress.sh, which is the documented entry point.

The flow per (design, part) is the same one apio runs:

    yosys -> nextpnr-xilinx (--post-route) -> fasm2frames -> xc7frames2bit

What makes it a *regression* suite rather than a smoke test is the last step:
the metrics that come out (fmax, utilisation, runtime, bitstream size) are
compared against `baselines/<platform>.json`, which is only ever refreshed
explicitly, in the same change that moved the numbers.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DESIGNS_DIR = HERE / "designs"
BASELINES_DIR = HERE / "baselines"

# metric -> (warn threshold, fail threshold) as a relative change where a
# POSITIVE number means "worse". None disables that level.
TOLERANCES = {
    "fmax_mhz": (0.02, 0.05),      # a drop in fmax is worse
    "luts": (0.10, 0.20),
    "ffs": (0.10, 0.20),
    "brams": (0.10, 0.20),
    "dsps": (0.10, 0.20),
    "bit_bytes": (0.0, None),      # any change is worth a look, never fatal
    "pnr_seconds": (0.50, None),   # runners vary too much to ever fail on this
}
# metrics where a bigger number is BETTER (so a drop is the regression)
HIGHER_IS_BETTER = {"fmax_mhz"}


class FlowError(RuntimeError):
    """The toolchain failed to produce a bitstream (always a hard failure)."""


@dataclass
class Design:
    name: str
    top: str
    description: str
    parts: list[str]
    source: Path
    synth_opts: str = ""

    @classmethod
    def load(cls, name: str) -> "Design":
        meta_path = DESIGNS_DIR / name / "meta.json"
        if not meta_path.exists():
            raise SystemExit(f"no such design: {name} ({meta_path} missing)")
        meta = json.loads(meta_path.read_text())
        return cls(
            name=name,
            top=meta["top"],
            description=meta.get("description", ""),
            parts=meta.get("parts", []),
            source=DESIGNS_DIR / name / "design.v",
            synth_opts=meta.get("synth_opts", ""),
        )


@dataclass
class Package:
    """An extracted package tree, plus how to invoke its tools."""

    root: Path
    platform: str
    _tmp: tempfile.TemporaryDirectory | None = field(default=None, repr=False)

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
                "this is a windows package: regression under wine is not wired yet"
            )
        if not (root / "libexec" / "nextpnr-xilinx").exists():
            raise SystemExit(f"unrecognised package layout at {root}")

        host = subprocess.run(["uname", "-s"], capture_output=True, text=True).stdout.strip()
        platform = {"Darwin": "darwin-arm64", "Linux": "linux-x86-64"}.get(host)
        if platform is None:
            raise SystemExit(f"unsupported host: {host}")
        return cls(root=root, platform=platform, _tmp=tmp)

    def tool(self, name: str) -> str:
        """Prefer the package's own wrapper, like a user of `start` would."""
        candidate = self.root / "bin" / name
        return str(candidate) if candidate.exists() else name

    @property
    def db(self) -> Path:
        return self.root / "share" / "nextpnr" / "external" / "prjxray-db"

    def device(self, part: str) -> str:
        """The part with its speedgrade, e.g. xc7a35tcpg236 -> ...-1."""
        matches = sorted(d.name for d in (self.db / "artix7").glob(f"{part}-*") if d.is_dir())
        if not matches:
            raise SystemExit(f"part {part} not in the packaged prjxray-db")
        return matches[0]


def run(cmd: list[str], cwd: Path, what: str) -> float:
    """Run a flow step, returning how long it took. Raises on failure."""
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).splitlines()[-15:])
        raise FlowError(f"{what} failed (exit {proc.returncode})\n{tail}")
    return elapsed


# Runs inside nextpnr's embedded interpreter — the same --post-route hook apio
# uses for `apio report`, so a design that breaks here breaks apio too. The
# output path is prepended as an OUTPUT assignment, which keeps this a valid,
# readable python file instead of a format template full of escaped braces.
POST_ROUTE = '''\
import json

util = {}
for bel in ctx.getBels():
    if ctx.getBoundBelCell(bel):
        key = str(ctx.getBelType(bel))
        util[key] = util.get(key, 0) + 1

try:
    fmax = ctx.reportClockFmaxJson()
except Exception:                   # report it as missing, never break the flow
    fmax = ""

with open(OUTPUT, "w") as handle:
    json.dump({"utilization": util, "fmax": fmax}, handle)
'''


def worst_fmax(raw: str) -> float | None:
    """Smallest achieved clock frequency in nextpnr's post-route report.

    The report is a JSON object keyed by clock name; rather than pinning this
    to one exact schema, collect every plausible achieved-frequency number and
    keep the worst, which is the one that matters.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None

    found: list[float] = []

    def walk(node, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, key.lower())
        elif isinstance(node, list):
            for value in node:
                walk(value, key_hint)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            if any(word in key_hint for word in ("fmax", "achieved", "actual")):
                found.append(float(node))

    walk(data)
    return min(found) if found else None


def bucket(util: dict[str, int]) -> dict[str, int]:
    """Group raw bel types into the handful of numbers worth tracking."""
    groups = {"luts": ("LUT",), "ffs": ("FF",), "brams": ("RAMB",), "dsps": ("DSP",)}
    out = {name: 0 for name in groups}
    for bel_type, count in util.items():
        upper = bel_type.upper()
        for name, needles in groups.items():
            if any(needle in upper for needle in needles):
                out[name] += count
    return out


def build(pkg: Package, design: Design, part: str, workdir: Path) -> dict:
    """Run the full flow once and return its metrics."""
    workdir.mkdir(parents=True, exist_ok=True)
    device = pkg.device(part)
    netlist = workdir / f"{design.name}.json"
    fasm = workdir / f"{design.name}.fasm"
    frames = workdir / f"{design.name}.frames"
    bitstream = workdir / f"{design.name}.bit"
    xdc = workdir / f"{design.name}.xdc"
    metrics_file = workdir / "metrics.json"
    post_route = workdir / "post_route.py"

    xdc.write_text(
        subprocess.run(
            [sys.executable, str(REPO / "e2e" / "gen_xdc.py"), str(pkg.db), "artix7", part],
            capture_output=True, text=True, check=True,
        ).stdout
    )
    post_route.write_text(f"OUTPUT = {str(metrics_file)!r}\n" + POST_ROUTE)

    run(
        ["yosys", "-q", "-p",
         f"synth_xilinx -arch xc7 -top {design.top} {design.synth_opts}; "
         f"write_json {netlist}", str(design.source)],
        workdir, "yosys",
    )
    pnr_seconds = run(
        [pkg.tool("nextpnr-xilinx"),
         "--chipdb", str(pkg.root / "chipdb" / f"{part}.bin"),
         "--xdc", str(xdc), "--json", str(netlist), "--fasm", str(fasm),
         "--post-route", str(post_route), "--router", "router2", "-q"],
        workdir, "nextpnr-xilinx",
    )
    if not metrics_file.exists():
        raise FlowError("the --post-route script did not run (apio report would break)")

    with open(frames, "w") as handle:
        proc = subprocess.run(
            [pkg.tool("fasm2frames"), "--part", device,
             "--db-root", str(pkg.db / "artix7"), str(fasm)],
            cwd=workdir, stdout=handle, stderr=subprocess.PIPE, text=True,
        )
    if proc.returncode != 0 or frames.stat().st_size == 0:
        tail = "\n".join(proc.stderr.splitlines()[-15:])
        raise FlowError(f"fasm2frames failed\n{tail}")

    run(
        [pkg.tool("xc7frames2bit"),
         "--part_file", str(pkg.db / "artix7" / device / "part.yaml"),
         "--part_name", device, "--frm_file", str(frames),
         "--output_file", str(bitstream)],
        workdir, "xc7frames2bit",
    )
    if bitstream.stat().st_size == 0:
        raise FlowError("empty bitstream")

    raw = json.loads(metrics_file.read_text())
    metrics = {
        "fmax_mhz": worst_fmax(raw.get("fmax", "")),
        **bucket(raw.get("utilization", {})),
        "pnr_seconds": round(pnr_seconds, 2),
        "bit_bytes": bitstream.stat().st_size,
    }
    return metrics


def tool_versions(pkg: Package) -> dict:
    def first_line(cmd: list[str]) -> str:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            return (proc.stdout or proc.stderr).strip().splitlines()[0]
        except (OSError, IndexError):
            return "unknown"

    return {
        "yosys": first_line(["yosys", "-V"]),
        "nextpnr": first_line([pkg.tool("nextpnr-xilinx"), "--version"]),
    }


def compare(current: dict, previous: dict | None) -> tuple[str, list[str]]:
    """Return (status, notes) for one design/part against its baseline."""
    if previous is None:
        return "NEW", ["no baseline recorded yet"]

    status, notes = "OK", []
    for metric, (warn_at, fail_at) in TOLERANCES.items():
        now, before = current.get(metric), previous.get(metric)
        if now is None or before in (None, 0):
            continue
        delta = (now - before) / abs(before)          # what the number did
        worse = -delta if metric in HIGHER_IS_BETTER else delta
        if fail_at is not None and worse > fail_at:
            status = "FAIL"
        elif warn_at is not None and worse > warn_at:
            if status != "FAIL":
                status = "WARN"
        else:
            continue
        notes.append(f"{metric}: {before} -> {now} ({delta:+.1%}, worse)")
    return status, notes


def main() -> int:
    parser = argparse.ArgumentParser(prog="regress.sh", description=__doc__)
    parser.add_argument("package", type=Path, help="package directory or .tgz")
    parser.add_argument("--design", action="append", help="restrict to this design (repeatable)")
    parser.add_argument("--part", action="append", help="restrict to this part (repeatable)")
    parser.add_argument("--update-baseline", action="store_true",
                        help="record the measured values as the new baseline")
    parser.add_argument("--json", type=Path, help="also write the report as JSON")
    parser.add_argument("--keep", action="store_true", help="keep the work directory")
    args = parser.parse_args()

    pkg = Package.open(args.package)
    names = args.design or sorted(d.name for d in DESIGNS_DIR.iterdir() if d.is_dir())
    designs = [Design.load(name) for name in names]
    versions = tool_versions(pkg)

    baseline_path = BASELINES_DIR / f"{pkg.platform}.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}

    print(f"platform : {pkg.platform}")
    print(f"yosys    : {versions['yosys']}")
    print(f"nextpnr  : {versions['nextpnr']}")
    print()

    work_root = Path(tempfile.mkdtemp(prefix="openxc7-regress-work-"))
    report, worst = {}, "OK"
    try:
        for design in designs:
            for part in (args.part or design.parts):
                label = f"{design.name}/{part}"
                previous = baseline.get(design.name, {}).get(part)
                try:
                    metrics = build(pkg, design, part, work_root / design.name / part)
                except FlowError as exc:
                    worst = "FAIL"
                    report[label] = {"status": "FAIL", "error": str(exc)}
                    print(f"FAIL {label}\n     {str(exc).splitlines()[0]}")
                    continue

                status, notes = compare(metrics, previous)
                if previous and previous.get("env", {}) != versions:
                    notes.append("baseline was recorded with different tool versions")
                    if status == "OK":
                        status = "WARN"
                if status == "FAIL" or (status == "WARN" and worst == "OK"):
                    worst = status
                report[label] = {"status": status, "metrics": metrics, "notes": notes}

                summary = (f"fmax={metrics['fmax_mhz']}" if metrics["fmax_mhz"] else "fmax=n/a")
                print(f"{status:<4} {label:<28} {summary} luts={metrics['luts']} "
                      f"ffs={metrics['ffs']} brams={metrics['brams']} dsps={metrics['dsps']} "
                      f"pnr={metrics['pnr_seconds']}s")
                for note in notes:
                    print(f"       {note}")

                if args.update_baseline:
                    baseline.setdefault(design.name, {})[part] = {**metrics, "env": versions}
    finally:
        if args.keep:
            print(f"\nwork directory kept at {work_root}")
        else:
            shutil.rmtree(work_root, ignore_errors=True)

    if args.update_baseline:
        BASELINES_DIR.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
        print(f"\nbaseline written: {baseline_path.relative_to(REPO)}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"\nregression: {worst}")
    return 1 if worst == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
