"""Entry point of the regression suite: discover, run, judge, report.

    python3 regress/harness <package> [options]

Invoked through scripts/regress.sh, which is the documented interface.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The repo root, so the harness shares pack.families with the packer — the
# part->family rule must have ONE python source (nix has its own copy of the
# prefix table in nextpnr-xilinx-chipdb.nix; that is the whole duplication).
sys.path.insert(1, str(Path(__file__).resolve().parent.parent.parent))

import checks          # noqa: E402
import metrics as metrics_module  # noqa: E402
import reporting       # noqa: E402
import spec as spec_module        # noqa: E402
from flow import run as run_flow  # noqa: E402
from pkg import Package           # noqa: E402

HARNESS_DIR = Path(__file__).resolve().parent
REGRESS_DIR = HARNESS_DIR.parent
REPO = REGRESS_DIR.parent
TESTS_DIR = REGRESS_DIR / "tests"
BASELINES_DIR = REGRESS_DIR / "baselines"


def select(specs, args):
    chosen = specs
    if args.test:
        wanted = set(args.test)
        unknown = wanted - {item.name for item in specs}
        if unknown:
            raise SystemExit(f"no such test(s): {sorted(unknown)}")
        chosen = [item for item in chosen if item.name in wanted]
    if args.tier:
        chosen = [item for item in chosen if item.tier <= args.tier]
    if args.tag:
        chosen = [item for item in chosen if set(args.tag) & set(item.tags)]
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(prog="regress.sh", description=__doc__)
    parser.add_argument("package", type=Path, nargs="?", help="package directory or .tgz")
    parser.add_argument("--test", action="append", help="run only this test (repeatable)")
    parser.add_argument("--part", action="append", help="run only this part (repeatable)")
    parser.add_argument("--tier", type=int, help="run tiers up to this one")
    parser.add_argument("--tag", action="append", help="run tests carrying this tag")
    parser.add_argument("--list", action="store_true", help="show the catalogue and exit")
    parser.add_argument("--explain", metavar="TEST",
                        help="print what a test is for (its README) and exit")
    parser.add_argument("--update-baseline", action="store_true",
                        help="record the measured values as the new baseline")
    parser.add_argument("--json", type=Path, help="write the report as JSON")
    parser.add_argument("--markdown", type=Path, help="write the report as markdown")
    parser.add_argument("--keep", action="store_true", help="keep the work directory")
    args = parser.parse_args()

    try:
        specs = select(spec_module.load_all(TESTS_DIR, REPO), args)
    except spec_module.SpecError as exc:
        raise SystemExit(f"invalid test declaration:\n  {exc}")

    if args.explain:
        for spec in specs:
            if spec.name == args.explain:
                print(spec.readme.read_text())
                return 0
        raise SystemExit(f"no such test: {args.explain}")
    if args.list:
        reporting.catalogue(specs)
        return 0
    if args.package is None:
        parser.error("a package is required (or use --list)")
    if not specs:
        raise SystemExit("no tests selected")

    package = Package.open(args.package)
    versions = package.versions()
    baseline_path = BASELINES_DIR / f"{package.platform}.json"
    baseline = {}
    if baseline_path.exists():
        import json
        baseline = json.loads(baseline_path.read_text())

    print(f"platform : {package.platform}")
    print(f"yosys    : {versions['yosys']}")
    print(f"nextpnr  : {versions['nextpnr']}")
    print(f"tests    : {len(specs)}\n")

    work_root = Path(tempfile.mkdtemp(prefix="openxc7-regress-"))
    entries = []
    try:
        for spec in specs:
            # Pinned third-party sources are fetched, not committed. A test
            # whose external tree is absent is reported (SKIP, never a gate),
            # unless the run asked for that test by name — then it is an
            # error, because silence is exactly what was not wanted.
            if spec.missing_external is not None:
                remedio = ("external sources not fetched "
                           f"({spec.missing_external.name}): run scripts/fetch-demos.sh")
                if args.test and spec.name in args.test:
                    raise SystemExit(f"{spec.name}: {remedio}")
                entries.append({
                    "test": spec.name, "part": "-", "status": "SKIP",
                    "description": spec.description, "metrics": {},
                    "findings": [], "notes": [remedio], "error": "",
                    "log_tail": "",
                })
                continue
            for part in (args.part or spec.parts):
                result = run_flow(spec, package, part, work_root / spec.name / part, REPO)
                measured = metrics_module.compute(result) if result.ok else {}
                findings = checks.evaluate(spec, result, measured)

                status, notes = "OK", []
                if findings:
                    status = "FAIL"
                elif spec.track_metrics and not spec.expected_to_fail:
                    previous = baseline.get(spec.name, {}).get(part)
                    status, notes = metrics_module.compare(measured, previous, spec.tolerances)
                    if previous and previous.get("env", {}) != versions:
                        notes.append("baseline recorded with different tool versions")
                        status = "WARN" if status == "OK" else status

                cola = ""
                if status == "FAIL" and not result.ok:
                    cola = "\n".join(result.log.splitlines()[-12:])
                entries.append({
                    "test": spec.name, "part": part, "status": status,
                    "description": spec.description, "metrics": measured,
                    "findings": findings, "notes": notes, "error": result.error,
                    "log_tail": cola,
                })
                # A baseline refresh records every run that completed its flow
                # and held its expectations — INCLUDING metric drift beyond
                # tolerance. That is the point of refreshing on a toolchain
                # bump: the drift is deliberate, it is printed loudly here,
                # and the baseline diff in the bump's change is what a human
                # reviews. What is never recorded is a broken flow or a
                # violated expectation (findings).
                if args.update_baseline and measured and not findings:
                    baseline.setdefault(spec.name, {})[part] = {**measured, "env": versions}
    finally:
        if args.keep:
            print(f"\nwork directory kept at {work_root}")
        else:
            shutil.rmtree(work_root, ignore_errors=True)

    reporting.console(entries)

    if args.update_baseline:
        import json
        BASELINES_DIR.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
        print(f"\nbaseline written: {baseline_path.relative_to(REPO)}")
    if args.json:
        reporting.to_json(entries, versions, args.json)
    if args.markdown:
        reporting.to_markdown(entries, versions, package.platform, args.markdown)

    summary = reporting.worst([entry["status"] for entry in entries])
    print(f"\nregression: {summary}")
    if args.update_baseline:
        # Refreshing rewrites the reference, so metric drift cannot "fail"
        # the run — only a broken flow or violated expectation can.
        broken = [e for e in entries if e["findings"]]
        if broken:
            print(f"NOT re-baselined ({len(broken)} broken): "
                  + ", ".join(f"{e['test']}/{e['part']}" for e in broken))
        return 1 if broken else 0
    return 1 if summary == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
