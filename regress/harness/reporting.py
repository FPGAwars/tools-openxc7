"""Rendering results: console for humans, JSON for machines, markdown for CI.

Separated from the engine so that a new output format never touches how tests
run — the CI job summary and the terminal read the same data.
"""

from __future__ import annotations

import json
from pathlib import Path

SEVERITY = {"OK": 0, "NEW": 1, "WARN": 2, "FAIL": 3}
_COLOUR = {"OK": "\033[0;32m", "NEW": "\033[0;34m", "WARN": "\033[1;33m", "FAIL": "\033[0;31m"}
_RESET = "\033[0m"


def worst(statuses) -> str:
    return max(statuses, key=lambda status: SEVERITY[status], default="OK")


def line(entry: dict, colour: bool = True) -> str:
    status = entry["status"]
    label = f"{entry['test']}/{entry['part']}"
    metrics = entry.get("metrics") or {}
    if metrics:
        fmax = metrics.get("fmax_mhz")
        summary = (f"fmax={fmax if fmax is not None else 'n/a'} "
                   f"luts={metrics.get('luts')} ffs={metrics.get('ffs')} "
                   f"brams={metrics.get('brams')} dsps={metrics.get('dsps')} "
                   f"pnr={metrics.get('pnr_seconds')}s")
    else:
        summary = entry.get("error", "")
    tag = f"{_COLOUR[status]}{status:<4}{_RESET}" if colour else f"{status:<4}"
    return f"{tag} {label:<34} {summary}"


def console(entries: list[dict]) -> None:
    for entry in entries:
        print(line(entry))
        for note in entry.get("findings", []) + entry.get("notes", []):
            print(f"       {note}")
        # A failed flow without its output is undebuggable; show the tail of
        # the step that broke.
        for linea in (entry.get("log_tail") or "").splitlines():
            print(f"       │ {linea}")


def catalogue(specs) -> None:
    print(f"{'test':<16} {'tier':<5} {'parts':<7} tags / description")
    for spec in specs:
        tags = ",".join(spec.tags)
        print(f"{spec.name:<16} {spec.tier:<5} {len(spec.parts):<7} "
              f"{tags + ' ' if tags else ''}{spec.description}")
        for item in spec.exercises:
            print(f"{'':<30} · {item}")


def to_json(entries: list[dict], versions: dict, path: Path) -> None:
    payload = {
        "tools": versions,
        "summary": worst([entry["status"] for entry in entries]),
        "results": entries,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def to_markdown(entries: list[dict], versions: dict, platform: str, path: Path) -> None:
    rows = ["## Regression — " + platform, "",
            f"`{versions.get('yosys', '?')}`", f"`{versions.get('nextpnr', '?')}`", "",
            "| Status | Test | Part | fmax | LUT | FF | BRAM | DSP | pnr |",
            "|---|---|---|---|---|---|---|---|---|"]
    for entry in entries:
        metrics = entry.get("metrics") or {}
        cell = lambda key: ("n/a" if metrics.get(key) is None else metrics.get(key))
        rows.append(
            f"| {entry['status']} | {entry['test']} | {entry['part']} | "
            f"{cell('fmax_mhz')} | {cell('luts')} | "
            f"{cell('ffs')} | {cell('brams')} | "
            f"{cell('dsps')} | {cell('pnr_seconds')} |"
        )
    problems = [entry for entry in entries if entry["status"] in ("FAIL", "WARN")]
    if problems:
        rows += ["", "### Findings", ""]
        for entry in problems:
            for note in entry.get("findings", []) + entry.get("notes", []):
                rows.append(f"- **{entry['test']}/{entry['part']}** — {note}")
    path.write_text("\n".join(rows) + "\n")
