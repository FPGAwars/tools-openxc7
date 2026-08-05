#!/usr/bin/env bash
#
# bump-remote-config.sh -- update package tags in apio's remote-config jsonc.
#
# Edits the "tag" field INSIDE the named package block only, preserving
# comments and formatting (the file is jsonc, hand-maintained by the apio
# project). No-op (exit 0, says so) when the tag is already the target.
#
# Usage:
#   scripts/bump-remote-config.sh <remote-config.jsonc> openxc7=<tag> [definitions=<tag>] ...

set -euo pipefail
FILE=${1:?usage: bump-remote-config.sh <remote-config.jsonc> <package>=<tag> ...}
shift
[ $# -gt 0 ] || { echo "no <package>=<tag> arguments" >&2; exit 2; }

python3 - "$FILE" "$@" <<'PYEOF'
import re, sys

path = sys.argv[1]
text = open(path).read()
changed = []
for spec in sys.argv[2:]:
    package, _, tag = spec.partition("=")
    if not tag:
        sys.exit(f"malformed argument (want package=tag): {spec}")
    if not re.fullmatch(r"20\d\d-\d\d-\d\d", tag):
        sys.exit(f"{package}: tag must be a YYYY-MM-DD date, got {tag!r}")
    # the first "tag" inside the package's block
    pattern = re.compile(
        rf'("{package}":\s*\{{.*?"tag":\s*")([^"]+)(")', re.S)
    m = pattern.search(text)
    if not m:
        sys.exit(f"package block not found in {path}: {package}")
    if m.group(2) == tag:
        print(f"{package}: already {tag} (no-op)")
        continue
    print(f"{package}: {m.group(2)} -> {tag}")
    text = text[:m.start(2)] + tag + text[m.end(2):]
    changed.append(package)

open(path, "w").write(text)
print(f"changed: {', '.join(changed) if changed else 'nothing'}")
PYEOF
