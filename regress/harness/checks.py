"""Expectations: turning what a test declared into pass/fail findings.

Every entry of a test's `expect` block dispatches to one function here. Adding
a new kind of expectation is therefore one function plus its key in
`spec.EXPECT_KEYS` — the engine and the tests themselves stay untouched.

A check returns the list of things that went wrong; an empty list means it
held.
"""

from __future__ import annotations

import re

REGISTRY = {}


def check(name: str):
    def register(function):
        REGISTRY[name] = function
        return function
    return register


@check("status")
def _status(expected: str, spec, result, metrics) -> list[str]:
    if expected == "fail":
        if result.ok:
            return ["expected the flow to fail, but it completed"]
        return []
    if not result.ok:
        detail = result.error or "unknown failure"
        return [f"flow failed at {result.failed_step or '?'}: {detail}"]
    return []


@check("log_contains")
def _log_contains(patterns, spec, result, metrics) -> list[str]:
    return [f"log does not contain {pattern!r}" for pattern in patterns
            if not re.search(pattern, result.log, re.IGNORECASE)]


@check("log_absent")
def _log_absent(patterns, spec, result, metrics) -> list[str]:
    return [f"log contains {pattern!r}, which it should not" for pattern in patterns
            if re.search(pattern, result.log, re.IGNORECASE)]


def _matches(actual: int, requirement) -> bool:
    if isinstance(requirement, int):
        return actual == requirement
    match = re.fullmatch(r"\s*(>=|<=|>|<|==)?\s*(\d+)\s*", str(requirement))
    if not match:
        raise ValueError(f"malformed requirement: {requirement!r}")
    operator, value = match.group(1) or "==", int(match.group(2))
    return {
        "==": actual == value, ">=": actual >= value, "<=": actual <= value,
        ">": actual > value, "<": actual < value,
    }[operator]


@check("primitives")
def _primitives(requirements, spec, result, metrics) -> list[str]:
    """Assert what synthesis inferred, counted on the netlist itself.

    This is what makes a design's *intent* enforceable: `dsp48` claiming to
    exercise the DSP48E1 model is worthless if a yosys change quietly maps it
    to LUTs instead.
    """
    findings = []
    for cell_type, requirement in requirements.items():
        actual = result.cells.get(cell_type, 0)
        try:
            if not _matches(actual, requirement):
                findings.append(f"{cell_type}: expected {requirement}, netlist has {actual}")
        except ValueError as exc:
            findings.append(str(exc))
    return findings


@check("modules")
def _modules(requirement, spec, result, metrics) -> list[str]:
    """How many modules survived synthesis — i.e. whether hierarchy is intact.

    synth_xilinx does not flatten by default, and a flat netlist would quietly
    stop exercising the hierarchical frontend path that once crashed.
    """
    actual = len(result.modules)
    try:
        if not _matches(actual, requirement):
            return [f"modules: expected {requirement}, netlist has {actual} "
                    f"({', '.join(result.modules[:4])})"]
    except ValueError as exc:
        return [str(exc)]
    return []


@check("artifacts")
def _artifacts(names, spec, result, metrics) -> list[str]:
    findings = []
    for name in names:
        path = result.artifacts.get(name)
        if path is None:
            findings.append(f"artifact '{name}' was not produced")
        elif not path.exists() or path.stat().st_size == 0:
            findings.append(f"artifact '{name}' is empty")
    return findings


@check("metrics_present")
def _metrics_present(names, spec, result, metrics) -> list[str]:
    """Guard the reporting path itself: a metric silently going missing (an
    empty clock table, say) is a regression even when the bitstream is fine."""
    return [f"metric '{name}' was not reported" for name in names
            if metrics.get(name) is None]


def evaluate(spec, result, metrics) -> list[str]:
    """Run every declared expectation, plus the implicit one: it must pass."""
    findings = []
    expectations = dict(spec.expect)
    expectations.setdefault("status", "pass")
    for name, value in expectations.items():
        findings.extend(REGISTRY[name](value, spec, result, metrics))
    return findings
