#!/usr/bin/env python3
"""Check the workflow graph without running it: every `uses:` of a local
reusable workflow must supply the inputs that workflow declares (and no
others), and every `needs.<job>.outputs.<name>` must name a job of the same
file that actually declares that output.

Both are silent failures in Actions -- an unknown input is ignored and an
undeclared output evaluates to the empty string -- so they surface as a
mystery halfway through a two-hour release build. Run over the checked-out
tree (no network, no Actions):

    scripts/check-workflows.py [repo-root]
"""

import re
import sys
from pathlib import Path

import yaml


ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else
            Path(__file__).resolve().parent.parent).resolve()
# Every workflow in the tree, so a new one is covered the day it lands.
FILES = sorted(
    str(path.relative_to(ROOT))
    for path in (ROOT / ".github/workflows").glob("*.y*ml")
)
OUTPUT_REF = re.compile(r"needs\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)")

if not FILES:
    sys.exit(f"no workflows under {ROOT}/.github/workflows")


def load(relative):
    with (ROOT / relative).open(encoding="utf-8") as source:
        return yaml.load(source, Loader=yaml.BaseLoader)


def call_interface(workflow):
    event = workflow.get("on", {}).get("workflow_call", {}) or {}
    return event.get("inputs", {}) or {}, event.get("outputs", {}) or {}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


workflows = {name: load(name) for name in FILES}
errors = []
calls = 0
references = 0
for name, workflow in workflows.items():
    jobs = workflow.get("jobs", {})
    job_outputs = {}
    for job_name, job in jobs.items():
        uses = job.get("uses", "")
        if uses.startswith("./.github/workflows/"):
            target = uses[2:]
            if target not in workflows:
                errors.append(f"{name}:{job_name}: unchecked local target {target}")
                continue
            accepted, outputs = call_interface(workflows[target])
            supplied = job.get("with", {}) or {}
            unknown = sorted(set(supplied) - set(accepted))
            if unknown:
                errors.append(
                    f"{name}:{job_name}: {target} rejects inputs {unknown}"
                )
            missing = sorted(
                key for key, spec in accepted.items()
                if spec.get("required") == "true" and key not in supplied
            )
            if missing:
                errors.append(
                    f"{name}:{job_name}: {target} misses required inputs {missing}"
                )
            job_outputs[job_name] = set(outputs)
            calls += 1
        else:
            job_outputs[job_name] = set((job.get("outputs", {}) or {}).keys())

    for value in strings(workflow):
        for producer, output in OUTPUT_REF.findall(value):
            references += 1
            if producer not in jobs:
                errors.append(f"{name}: needs unknown job {producer}")
            elif output not in job_outputs.get(producer, set()):
                errors.append(
                    f"{name}: needs.{producer}.outputs.{output} is undeclared"
                )

for name in FILES:
    print(f"parsed: {name}")
if errors:
    print("interface errors:")
    print("\n".join(f"- {error}" for error in errors))
    raise SystemExit(1)
print(f"cross-check: OK ({calls} local calls, {references} output references)")
