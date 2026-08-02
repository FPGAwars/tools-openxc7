#!/usr/bin/env bash
#
# check-pins.sh -- assert the installer pins are aligned with reality.
#
# Three sources must agree for every tool this repo installs:
#
#   1. lib/common.sh          what ./install.sh actually downloads
#   2. GitHub releases/latest the latest PROMOTED release (nightly
#                             prereleases are excluded by design, which is
#                             exactly why releases are published with
#                             --prerelease --latest=false until validated)
#   3. apio's remote-config   what apio installs for end users
#
# Usage:
#   scripts/check-pins.sh              # exit != 0 if anything drifted
#   scripts/check-pins.sh --report     # print the table, always exit 0
#
# Env: APIO_REMOTE_CONFIG_URL to point at another remote-config;
#      GH_TOKEN / GITHUB_TOKEN are used if set (API rate limits).

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MODE="check"
case "${1:-}" in
    --report) MODE="report" ;;
    -h|--help) sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    "") ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
esac

python3 - "$REPO_ROOT" "$MODE" <<'PYEOF'
import json, os, re, sys, urllib.error, urllib.request

repo_root, mode = sys.argv[1], sys.argv[2]

REMOTE_CONFIG = os.environ.get(
    "APIO_REMOTE_CONFIG_URL",
    "https://raw.githubusercontent.com/FPGAwars/apio/main/remote-config/apio-1.5.x.jsonc",
)
# pin name in lib/common.sh -> (github repo, key in apio's remote-config)
TOOLS = {
    "OPENXC7_DATE": ("FPGAwars/tools-openxc7", "openxc7"),
    "OSS_CAD_SUITE_DATE": ("FPGAwars/tools-oss-cad-suite", "oss-cad-suite"),
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tools-openxc7-check-pins"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def local_pins():
    """Read the defaults out of lib/common.sh (VAR="${VAR:-YYYY-MM-DD}")."""
    text = open(os.path.join(repo_root, "lib", "common.sh")).read()
    pins = {}
    for var in TOOLS:
        m = re.search(rf'^{var}=.*?(\d{{4}}-\d{{2}}-\d{{2}})', text, re.M)
        if m:
            pins[var] = m.group(1)
    return pins


def apio_pins():
    """packages.<key>.release.tag from apio's remote-config (jsonc)."""
    raw = get(REMOTE_CONFIG)
    stripped = "\n".join(
        "" if ln.lstrip().startswith("//") else ln for ln in raw.splitlines()
    )
    data = json.loads(stripped)["packages"]
    return {key: data[key]["release"]["tag"] for _, key in TOOLS.values()}


try:
    local = local_pins()
    apio = apio_pins()
    promoted = {
        repo: json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest"))["tag_name"]
        for repo, _ in TOOLS.values()
    }
except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as e:
    print(f"could not resolve the published state: {e}", file=sys.stderr)
    sys.exit(0 if mode == "report" else 2)

print(f"{'tool':<22} {'installer':<12} {'promoted':<12} {'apio':<12} status")
drift = []
for var, (repo, key) in TOOLS.items():
    got, pub, ap = local.get(var, "?"), promoted[repo], apio[key]
    aligned = got == pub == ap
    if not aligned:
        drift.append((var, got, pub, ap))
    print(f"{key:<22} {got:<12} {pub:<12} {ap:<12} {'OK' if aligned else 'DRIFT'}")

if not drift:
    print("\nall pins aligned")
    sys.exit(0)

print("", file=sys.stderr)
for var, got, pub, ap in drift:
    print(f"DRIFT {var}: installer={got} promoted={pub} apio={ap}", file=sys.stderr)
print(
    "\nAfter promoting a release candidate, bump lib/common.sh and apio's "
    "remote-config to the promoted tag.",
    file=sys.stderr,
)
sys.exit(0 if mode == "report" else 1)
PYEOF
