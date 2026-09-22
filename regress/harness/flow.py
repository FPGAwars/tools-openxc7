"""Running one test on one part: the flow, and everything it observes.

The flow is exactly the one apio runs — yosys → nextpnr-xilinx (with the
`--report` JSON that backs `apio report`) → fasm2frames → xc7frames2bit —
truncated at whatever stage the test asked for. The place-and-route step speaks
the command line of the package's schema: schema 7 is the himbaechel xilinx
uarch (the part in --device, the XDC and FASM as uarch options, one chipdb
per die); schema 6 and 5 are the current engine.

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

from pack.families import family_of

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

    def __init__(self, workdir: Path, timeout: int = 900):
        self.workdir = workdir
        self.timeout = timeout
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
        # timeout: hangs are a REAL failure class here (the HeAP
        # legalise_placement_strict loop, seen twice); without a limit one
        # hanging test freezes the whole suite in CI.
        try:
            proc = subprocess.run(cmd, cwd=self.workdir, capture_output=True,
                                  text=True, stdin=subprocess.DEVNULL,
                                  env=entorno, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode(errors="replace")
            self.chunks.append(
                f"=== {name} TIMED OUT after {self.timeout}s ===\n{partial}")
            raise _StepFailed(
                name, f"{name} timed out after {self.timeout}s (hang-class)")
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
            [sys.executable, str(repo / "e2e" / "gen_xdc.py"), str(pkg.db), family_of(part), part],
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


def _pnr_command(spec, pkg, part: str, xdc: Path, netlist: Path, fasm: Path,
                 report: Path) -> list:
    """The place-and-route command line of the package's schema.

    Both write the metrics with --report, which is what apio reads (since
    apio#1048; the current engine's --post-route hook called
    ctx.reportClockFmaxJson(), a python binding the himbaechel uarch does
    not have).
    """
    if pkg.schema <= 6:
        return [
            *pkg.cmd("nextpnr-xilinx"),
            "--chipdb", str(pkg.chipdb(part)),
            "--xdc", str(xdc),
            "--json", str(netlist),
            "--fasm", str(fasm),
            "--report", str(report),
            "--router", spec.router,
            *spec.nextpnr_args,
        ]
    # The himbaechel uarch: the part goes in --device (the full name apio
    # knows, speed grade included), the XDC and FASM are uarch options, and
    # the chipdb is the one of the part's die.
    return [
        *pkg.cmd("nextpnr-xilinx"),
        "--device", pkg.device(part, strict=False),
        "--chipdb", str(pkg.chipdb(part)),
        "-o", f"xdc={xdc}",
        "-o", f"fasm={fasm}",
        "--json", str(netlist),
        "--report", str(report),
        "--router", spec.router,
        *spec.nextpnr_args,
    ]


def run(spec, pkg, part: str, workdir: Path, repo: Path) -> FlowResult:
    workdir.mkdir(parents=True, exist_ok=True)
    session = _Session(workdir, timeout=spec.timeout)
    result = FlowResult()

    netlist = workdir / "netlist.json"
    fasm = workdir / "design.fasm"
    frames = workdir / "design.frames"
    bitstream = workdir / "design.bit"
    report = workdir / "report.json"

    try:
        xdc = _write_constraints(spec, pkg, part, workdir, repo)

        # Verilog parameters from the declaration: chparam runs after the
        # sources are read (they are file arguments, read before -p) and
        # before synthesis, so one parametrised design.v can back several
        # tests — e.g. the congestion pair, same netlist shape with a
        # different permutation stride.
        chparams = "".join(
            f"chparam -set {name} {value} {spec.top}; "
            for name, value in spec.parameters.items()
        )
        session.step("yosys", [
            "yosys", "-p",
            f"{chparams}synth_xilinx -arch xc7 -top {spec.top} {spec.synth_opts}; "
            f"write_json {netlist}",
            *[str(source) for source in spec.sources],
        ])
        result.artifacts["netlist"] = netlist
        result.cells, result.modules = _count_cells(netlist)
        if spec.flow == "synth":
            return result

        result.pnr_seconds = round(session.step(
            "nextpnr-xilinx",
            _pnr_command(spec, pkg, part, xdc, netlist, fasm, report),
            env_extra=pkg.env_extra), 2)
        if not report.exists():
            raise _StepFailed(
                "nextpnr-xilinx",
                "the --report file was not written (this is the `apio report` path)")
        observed = json.loads(report.read_text())
        result.utilization = {
            bel_type: counts["used"]
            for bel_type, counts in observed.get("utilization", {}).items()
            if counts.get("used")
        }
        result.fmax_raw = json.dumps(observed.get("fmax", {}))
        result.artifacts["fasm"] = fasm
        if spec.flow == "pnr":
            return result

        device = pkg.device(part)
        session.step("fasm2frames", [
            *pkg.python_cmd(pkg.root / "libexec/fasm2frames"),
            "--part", device,
            "--db-root", str(pkg.db / family_of(part)), str(fasm),
        ], stdout_to=frames, env_extra=pkg.env_extra)
        if frames.stat().st_size == 0:
            raise _StepFailed("fasm2frames", "fasm2frames produced no frames")
        result.artifacts["frames"] = frames
        if spec.flow == "fasm":
            return result

        session.step("xc7frames2bit", [
            *pkg.cmd("xc7frames2bit"),
            "--part_file", str(pkg.db / family_of(part) / device / "part.yaml"),
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
