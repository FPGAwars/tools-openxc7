#!/usr/bin/env python3
"""Refresh a platform's regression baseline from a CI regress-report.json.

After a toolchain revision bump the L2 gate fails exactly as designed: every
baseline was recorded with the previous revision and metric drift is gated.
The authoritative numbers for the new revision are the ones the CI package
itself measured, and the platform jobs publish them as the
`regress-report-<platform>` artifact (regress-report.json). This tool turns
that report into the baseline update the harness's --update-baseline would
have written on that runner, so the refresh is reproducible and reviewable
in one diff instead of being retyped by hand.

Recorded: every entry whose flow completed and whose expectations held
(status OK/WARN/FAIL-by-drift, i.e. it has metrics and no findings).
Never recorded: broken flows, violated expectations (findings), SKIPs.
The env (tool versions) comes from the report's `tools`.

usage: scripts/regress-baseline-from-report.py <platform> <regress-report.json>
   e.g. scripts/regress-baseline-from-report.py darwin-arm64 regress-report.json
Prints every metric that moved beyond 5% (the human-review list) and writes
regress/baselines/<platform>.json.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METRIC_KEYS = ("fmax_mhz", "luts", "ffs", "brams", "dsps", "pnr_seconds", "bit_bytes")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[-5], file=sys.stderr)
        return 2
    platform, report_path = sys.argv[1], Path(sys.argv[2])
    baseline_path = REPO / "regress" / "baselines" / f"{platform}.json"
    report = json.loads(report_path.read_text())
    versions = report["tools"]
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}

    recorded, created, drift, skipped = 0, [], [], []
    for entry in report["results"]:
        metrics = entry.get("metrics") or {}
        if not metrics or entry.get("findings") or entry["status"] == "SKIP":
            skipped.append(f"{entry['test']}/{entry['part']} ({entry['status']})")
            continue
        # exactly what the harness records with --update-baseline (None included)
        new = {k: metrics[k] for k in METRIC_KEYS if k in metrics}
        new["env"] = versions
        previous = baseline.get(entry["test"], {}).get(entry["part"])
        if previous is None:
            created.append(f"{entry['test']}/{entry['part']}")
        else:
            for key in ("fmax_mhz", "luts", "ffs", "pnr_seconds"):
                if key in new and previous.get(key):
                    rel = abs(new[key] - previous[key]) / max(abs(previous[key]), 1e-9)
                    if rel > 0.05:
                        drift.append(f"{entry['test']}/{entry['part']}: {key} {previous[key]} -> {new[key]} ({rel*100:+.1f}%)")
        baseline.setdefault(entry["test"], {})[entry["part"]] = new
        recorded += 1

    baseline_path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    print(f"{platform}: {recorded} entries recorded -> {baseline_path.relative_to(REPO)}")
    print(f"  tools: {versions}")
    if created:
        print(f"  NEW ({len(created)}): " + ", ".join(created))
    if skipped:
        print(f"  not recorded ({len(skipped)}): " + ", ".join(skipped))
    print(f"  drift > 5% ({len(drift)}) — the list to review:")
    for d in drift:
        print("    " + d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
