"""Running one test on one part: the flow, and everything it observes.

The flow is exactly the one apio runs — yosys → nextpnr-xilinx (with the
`--post-route` hook that backs `apio report`) → fasm2frames → xc7frames2bit —
truncated at whatever stage the test asked for.

Nothing here decides whether a test passed: the runner only reports what
happened (log, artefacts, cells, utilisation, timing). Judgement lives in
`checks`, so a failing step is a normal outcome — negative tests need it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Runs inside nextpnr's embedded interpreter. The output path is prepended as
# an assignment, which keeps this readable python instead of a format template.
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


@dataclass
class FlowResult:
    ok: bool = True
    error: str = ""
    failed_step: str = ""
    log: str = ""
    artifacts: dict = field(default_factory=dict)
    cells: dict = field(default_factory=dict)
    modules: list = field(default_factory=list)
    utilization: dict = field(default_factory=dict)
    fmax_raw: str = ""
    pnr_seconds: float | None = None


class _Session:
    """Accumulates the log while running the steps of one flow."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.chunks: list[str] = []

    @property
    def log(self) -> str:
        return "\n".join(self.chunks)

    def step(self, name: str, cmd: list, stdout_to: Path | None = None,
             env_extra: dict | None = None) -> float:
        started = time.monotonic()
        entorno = {**os.environ, **(env_extra or {})}
        # Every std handle is a pipe, never a file and never a terminal. Under
        # wine the mingw python aborts at init_sys_streams with
        # "[WinError 6] Invalid handle" if stdout is a redirected file — real
        # Windows accepts it, so this is a wine-only quirk, and capturing the
        # output ourselves sidesteps it uniformly on every platform.
        proc = subprocess.run(cmd, cwd=self.workdir, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, env=entorno)
        if stdout_to is not None:
            stdout_to.write_text(proc.stdout or "")
            output = proc.stderr or ""
        else:
            output = (proc.stdout or "") + (proc.stderr or "")
        elapsed = time.monotonic() - started
        self.chunks.append(f"=== {name} (exit {proc.returncode}) ===\n{output}")
        if proc.returncode != 0:
            raise _StepFailed(name, f"{name} failed (exit {proc.returncode})")
        return elapsed


class _StepFailed(Exception):
    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step


def _write_constraints(spec, pkg, part, workdir: Path, repo: Path) -> Path:
    xdc = workdir / "constraints.xdc"
    if spec.constraints == "auto":
        generated = subprocess.run(
            [sys.executable, str(repo / "e2e" / "gen_xdc.py"), str(pkg.db), "artix7", part],
            capture_output=True, text=True,
        )
        if generated.returncode != 0:
            raise _StepFailed("constraints", f"gen_xdc.py failed: {generated.stderr.strip()}")
        body = generated.stdout
    else:
        body = (spec.directory / spec.constraints).read_text()
    if spec.xdc_extra:
        body += "\n" + "\n".join(spec.xdc_extra) + "\n"
    xdc.write_text(body)
    return xdc


def _count_cells(netlist: Path) -> dict:
    """Cell types instantiated by the DESIGN.

    yosys writes the whole Xilinx cell library into the JSON as blackbox
    modules, and those carry their own `$specify`/`$specrule` timing cells.
    Counting them would drown the primitives an assertion cares about (a
    handful of RAMB/DSP48E1) under dozens of library artefacts.
    """
    data = json.loads(netlist.read_text())
    counts: dict = {}
    modules: list[str] = []
    for name, module in data.get("modules", {}).items():
        attributes = module.get("attributes", {})
        if any(key in attributes for key in ("blackbox", "whitebox")):
            continue
        modules.append(name)
        for cell in module.get("cells", {}).values():
            kind = cell.get("type", "?")
            counts[kind] = counts.get(kind, 0) + 1
    return counts, modules


def run(spec, pkg, part: str, workdir: Path, repo: Path) -> FlowResult:
    workdir.mkdir(parents=True, exist_ok=True)
    session = _Session(workdir)
    result = FlowResult()

    netlist = workdir / "netlist.json"
    fasm = workdir / "design.fasm"
    frames = workdir / "design.frames"
    bitstream = workdir / "design.bit"
    metrics_file = workdir / "post_route.json"
    post_route = workdir / "post_route.py"
    post_route.write_text(f"OUTPUT = {str(metrics_file)!r}\n" + POST_ROUTE)

    try:
        xdc = _write_constraints(spec, pkg, part, workdir, repo)

        session.step("yosys", [
            "yosys", "-p",
            f"synth_xilinx -arch xc7 -top {spec.top} {spec.synth_opts}; "
            f"write_json {netlist}",
            *[str(source) for source in spec.sources],
        ])
        result.artifacts["netlist"] = netlist
        result.cells, result.modules = _count_cells(netlist)
        if spec.flow == "synth":
            return result

        result.pnr_seconds = round(session.step("nextpnr-xilinx", [
            *pkg.cmd("nextpnr-xilinx"),
            "--chipdb", str(pkg.chipdb(part)),
            "--xdc", str(xdc),
            "--json", str(netlist),
            "--fasm", str(fasm),
            "--post-route", str(post_route),
            "--router", spec.router,
            *spec.nextpnr_args,
        ], env_extra=pkg.env_extra), 2)
        result.artifacts["fasm"] = fasm
        if metrics_file.exists():
            observed = json.loads(metrics_file.read_text())
            result.utilization = observed.get("utilization", {})
            result.fmax_raw = observed.get("fmax", "")
        else:
            raise _StepFailed(
                "nextpnr-xilinx",
                "the --post-route script did not run (this is the `apio report` path)",
            )
        if spec.flow == "pnr":
            return result

        device = pkg.device(part)
        session.step("fasm2frames", [
            *pkg.python_cmd(pkg.root / "libexec/fasm2frames"),
            "--part", device,
            "--db-root", str(pkg.db / "artix7"), str(fasm),
        ], stdout_to=frames, env_extra=pkg.env_extra)
        if frames.stat().st_size == 0:
            raise _StepFailed("fasm2frames", "fasm2frames produced no frames")
        result.artifacts["frames"] = frames
        if spec.flow == "fasm":
            return result

        session.step("xc7frames2bit", [
            *pkg.cmd("xc7frames2bit"),
            "--part_file", str(pkg.db / "artix7" / device / "part.yaml"),
            "--part_name", device,
            "--frm_file", str(frames),
            "--output_file", str(bitstream),
        ], env_extra=pkg.env_extra)
        if bitstream.stat().st_size == 0:
            raise _StepFailed("xc7frames2bit", "empty bitstream")
        result.artifacts["bitstream"] = bitstream
        return result

    except _StepFailed as failure:
        result.ok = False
        result.error = str(failure)
        result.failed_step = failure.step
        return result
    finally:
        result.log = session.log
        # Always on disk: with --keep there is something to read, and a
        # failure is diagnosable without re-running the whole thing by hand.
        (workdir / "flow.log").write_text(session.log)
