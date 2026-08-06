"""Test declarations: the `test.json` schema, its defaults and its validation.

A test is a directory under `regress/tests/` containing a `test.json` and the
sources it needs. Everything here is data — the engine never knows about any
particular test — so adding one is dropping a folder, and the only code that
ever changes is this file when the *vocabulary* itself grows.

Validation is deliberately strict about unknown keys: a typo in a declaration
would otherwise silently disable a check, which is the worst failure mode a
test suite can have (it keeps reporting green).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PART = "xc7a35tcpg236"

FLOW_STAGES = ("synth", "pnr", "fasm", "bitstream")
EXPECT_KEYS = {
    "status", "log_contains", "log_absent", "primitives", "modules",
    "artifacts", "metrics_present",
}
TOP_LEVEL_KEYS = {
    "description", "exercises", "why", "tier", "tags", "sources", "top",
    "parts", "constraints", "xdc_extra", "synth", "nextpnr", "flow", "expect",
    "metrics", "parameters", "timeout",
}


class SpecError(Exception):
    """A declaration is malformed. The message names the file and the field."""


@dataclass
class TestSpec:
    name: str
    directory: Path
    description: str
    readme: Path | None = None
    exercises: list[str] = field(default_factory=list)
    tier: int = 1
    tags: list[str] = field(default_factory=list)
    sources: list[Path] = field(default_factory=list)
    top: str = ""
    parts: list[str] = field(default_factory=list)
    constraints: str = "auto"
    xdc_extra: list[str] = field(default_factory=list)
    synth_opts: str = ""
    parameters: dict = field(default_factory=dict)
    nextpnr_args: list[str] = field(default_factory=list)
    router: str = "router2"
    flow: str = "bitstream"
    expect: dict = field(default_factory=dict)
    track_metrics: bool = True
    tolerances: dict = field(default_factory=dict)
    # Per-STEP wall-clock limit in seconds. Hangs are a real failure class
    # (the HeAP legalise loop); a hanging test must fail, not freeze CI.
    timeout: int = 900
    # A referenced file under regress/external/ that is not there (the pinned
    # third-party trees are fetched, not committed). The suite reports the
    # test as SKIP with the fetch command instead of failing everyone's run.
    missing_external: Path | None = None

    @property
    def expected_to_fail(self) -> bool:
        return self.expect.get("status", "pass") == "fail"


def _part_groups(repo: Path) -> dict[str, list[str]]:
    manifest = json.loads((repo / "chipdb-parts.json").read_text())
    every = [part for parts in manifest.values() for part in parts]
    # One group per family in the manifest (artix7, spartan7, ...): a test
    # can say "parts": "zynq7" and follow the manifest as it grows.
    return {"default": [DEFAULT_PART], "all": every, **manifest}


def _check_keys(where: str, given, allowed: set[str]) -> None:
    if not isinstance(given, dict):
        raise SpecError(f"{where}: expected an object, got {type(given).__name__}")
    unknown = set(given) - allowed
    if unknown:
        raise SpecError(
            f"{where}: unknown key(s) {sorted(unknown)}. Known keys: {sorted(allowed)}"
        )


def load(directory: Path, repo: Path) -> TestSpec:
    """Read and validate one test directory."""
    declaration = directory / "test.json"
    if not declaration.exists():
        raise SpecError(f"{directory}: no test.json")
    try:
        raw = json.loads(declaration.read_text())
    except ValueError as exc:
        raise SpecError(f"{declaration}: invalid JSON — {exc}") from exc

    _check_keys(str(declaration), raw, TOP_LEVEL_KEYS)
    if "description" not in raw:
        raise SpecError(f"{declaration}: 'description' is required")

    # Every test explains itself. A declaration says WHAT is checked; the
    # README says what the test is for, what a good result looks like and how
    # to read a bad one — the part a future reader (or a contributor from
    # openXC7) cannot reconstruct from the JSON.
    readme = directory / "README.md"
    if not readme.exists():
        raise SpecError(
            f"{directory}: README.md is required (what it probes, why it exists, "
            f"expected result, how to read a failure). See regress/README.md."
        )

    external_root = (repo / "regress" / "external").resolve()

    def _external(path: Path) -> bool:
        return path.resolve().is_relative_to(external_root)

    missing_external = None
    sources = [directory / name for name in raw.get("sources", [])]
    if not sources:
        sources = sorted(directory.glob("*.v"))
    for source in sources:
        if not source.exists():
            if _external(source):
                missing_external = source
            else:
                raise SpecError(f"{declaration}: source not found: {source.name}")
    if not sources:
        raise SpecError(f"{declaration}: no sources (no 'sources' key and no *.v)")

    parts = raw.get("parts", "default")
    if isinstance(parts, str):
        groups = _part_groups(repo)
        if parts not in groups:
            raise SpecError(
                f"{declaration}: unknown part group '{parts}' (known: {sorted(groups)})"
            )
        parts = groups[parts]
    if not isinstance(parts, list) or not parts:
        raise SpecError(f"{declaration}: 'parts' must be a non-empty list or a group name")

    flow = raw.get("flow", "bitstream")
    if flow not in FLOW_STAGES:
        raise SpecError(f"{declaration}: 'flow' must be one of {list(FLOW_STAGES)}")

    expect = raw.get("expect", {})
    _check_keys(f"{declaration}: expect", expect, EXPECT_KEYS)
    status = expect.get("status", "pass")
    if status not in ("pass", "fail"):
        raise SpecError(f"{declaration}: expect.status must be 'pass' or 'fail'")

    synth = raw.get("synth", {})
    _check_keys(f"{declaration}: synth", synth, {"opts"})
    parameters = raw.get("parameters", {})
    if not isinstance(parameters, dict) or not all(
            isinstance(v, (int, str)) for v in parameters.values()):
        raise SpecError(f"{declaration}: 'parameters' must map names to int/str values")
    nextpnr = raw.get("nextpnr", {})
    _check_keys(f"{declaration}: nextpnr", nextpnr, {"args", "router"})
    metrics = raw.get("metrics", {})
    _check_keys(f"{declaration}: metrics", metrics, {"track", "tolerances"})

    constraints = raw.get("constraints", "auto")
    if constraints != "auto" and not (directory / constraints).exists():
        if _external(directory / constraints):
            missing_external = directory / constraints
        else:
            raise SpecError(f"{declaration}: constraints file not found: {constraints}")

    return TestSpec(
        name=directory.name,
        directory=directory,
        description=raw["description"],
        readme=readme,
        exercises=raw.get("exercises", []),
        tier=int(raw.get("tier", 1)),
        tags=raw.get("tags", []),
        sources=sources,
        top=raw.get("top", directory.name),
        parts=parts,
        constraints=constraints,
        xdc_extra=raw.get("xdc_extra", []),
        synth_opts=synth.get("opts", ""),
        parameters=parameters,
        nextpnr_args=nextpnr.get("args", []),
        router=nextpnr.get("router", "router2"),
        flow=flow,
        expect=expect,
        track_metrics=metrics.get("track", True),
        tolerances=metrics.get("tolerances", {}),
        timeout=int(raw.get("timeout", 900)),
        missing_external=missing_external,
    )


def load_all(tests_dir: Path, repo: Path) -> list[TestSpec]:
    """Every test in the catalogue, sorted by name. Fails on the first bad one."""
    return [
        load(entry, repo)
        for entry in sorted(tests_dir.iterdir())
        if entry.is_dir() and not entry.name.startswith(".")
    ]
