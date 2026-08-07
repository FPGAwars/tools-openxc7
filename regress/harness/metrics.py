"""Turning a finished flow into the handful of numbers worth tracking, and
comparing them with the recorded baseline.

Metrics answer "did this get worse?", which is a different question from the
expectations in `checks` ("did this behave as declared?"). Only metrics need a
baseline, and only metrics have tolerances.
"""

from __future__ import annotations

import json

# metric -> (warn, fail) as a relative change where POSITIVE means worse.
# None disables that level.
DEFAULT_TOLERANCES = {
    "fmax_mhz": (0.02, 0.05),
    "luts": (0.10, 0.20),
    "ffs": (0.10, 0.20),
    "brams": (0.10, 0.20),
    "dsps": (0.10, 0.20),
    "bit_bytes": (0.0, None),      # any change is worth a look, never fatal
    # Wall-clock is a property of the MACHINE, not the toolchain: baselines
    # recorded on the build server or a dev mac made slower CI runners WARN
    # on half the suite for nothing. Informational by default; tests that
    # want a coarse thrash detector opt in with explicit tolerances.
    "pnr_seconds": (None, None),
}
HIGHER_IS_BETTER = {"fmax_mhz"}

_GROUPS = {"luts": ("LUT",), "ffs": ("FF",), "brams": ("RAMB",), "dsps": ("DSP",)}


def worst_fmax(raw: str) -> float | None:
    """The slowest achieved clock in nextpnr's post-route report.

    Rather than pinning this to one exact schema, collect every plausible
    achieved-frequency number and keep the worst — that is the one that
    decides whether a design still meets timing.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None

    found: list[float] = []

    def walk(node, hint: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, key.lower())
        elif isinstance(node, list):
            for value in node:
                walk(value, hint)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            if any(word in hint for word in ("fmax", "achieved", "actual")):
                found.append(float(node))

    walk(data)
    return min(found) if found else None


def bucket(utilization: dict) -> dict:
    counts = {name: 0 for name in _GROUPS}
    for bel_type, count in utilization.items():
        upper = bel_type.upper()
        for name, needles in _GROUPS.items():
            if any(needle in upper for needle in needles):
                counts[name] += count
    return counts


def compute(result) -> dict:
    bitstream = result.artifacts.get("bitstream")
    return {
        "fmax_mhz": worst_fmax(result.fmax_raw),
        **bucket(result.utilization),
        "pnr_seconds": result.pnr_seconds,
        "bit_bytes": bitstream.stat().st_size if bitstream else None,
    }


def compare(current: dict, baseline: dict | None, overrides: dict | None = None):
    """Return (status, notes) for one test/part against its baseline."""
    if baseline is None:
        return "NEW", ["no baseline recorded yet"]

    tolerances = dict(DEFAULT_TOLERANCES)
    for metric, limits in (overrides or {}).items():
        tolerances[metric] = (limits.get("warn"), limits.get("fail"))

    status, notes = "OK", []
    for metric, (warn_at, fail_at) in tolerances.items():
        now, before = current.get(metric), baseline.get(metric)
        if now is None or before in (None, 0):
            continue
        delta = (now - before) / abs(before)               # what the number did
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
