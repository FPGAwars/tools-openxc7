#!/usr/bin/env python3
"""Cross-check upload-artifact producers against download-artifact consumers.

A download whose name no producer uploads is not an error in Actions: the
step just finds nothing, and the job fails later with a missing file. That
is how the seed_from_artifact rename slipped through in 2026-08.
Names built from expressions and pattern downloads are reported, not judged.

    scripts/check-artifacts.py [repo-root]
"""
import sys, yaml, pathlib

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                    pathlib.Path(__file__).resolve().parent.parent)
up, down = {}, {}
for wf in sorted((root / ".github/workflows").glob("*.y*ml")):
    data = yaml.safe_load(wf.read_text())
    for job, spec in (data.get("jobs") or {}).items():
        for step in (spec.get("steps") or []):
            uses = (step.get("uses") or "")
            with_ = step.get("with") or {}
            if uses.startswith("actions/upload-artifact"):
                up.setdefault(with_.get("name", "<no name>"), []).append(f"{wf.name}:{job}")
            if uses.startswith("actions/download-artifact"):
                key = with_.get("name") or f"pattern:{with_.get('pattern','<none>')}"
                down.setdefault(key, []).append(f"{wf.name}:{job}")
print("UPLOADS:")
for k, v in sorted(up.items()):
    print(f"  {k:34s} <- {', '.join(v)}")
print("DOWNLOADS:")
for k, v in sorted(down.items()):
    print(f"  {k:34s} -> {', '.join(v)}")
unmatched = [k for k in down if not k.startswith("pattern:") and k not in up
             and "${{" not in k]
print("UNMATCHED DOWNLOADS:", unmatched or "none")
sys.exit(1 if unmatched else 0)
