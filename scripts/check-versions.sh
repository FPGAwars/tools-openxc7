#!/usr/bin/env bash
#
# check-versions.sh -- assert the published versions are aligned.
#
# Sources compared (this repo is an apio package; apio's remote-config is
# the single authority on what users install):
#
#   openxc7        latest PROMOTED release  <->  apio's remote-config tag
#                  (nightly prereleases are excluded by design: releases
#                  are published --prerelease --latest=false until a human
#                  promotes one)
#   oss-cad-suite  the version our CI VALIDATES the package against
#                  (scripts/ci-install-oss-cad-suite.sh)  <->  apio's
#                  remote-config tag -- a drift here means L1/L2 validate
#                  with different tools than users actually get
#
# Usage:
#   scripts/check-versions.sh              # exit != 0 if anything drifted
#   scripts/check-versions.sh --report     # print the table, always exit 0
#
# Env: APIO_REMOTE_CONFIG_URL to point at another remote-config;
#      GH_TOKEN / GITHUB_TOKEN are used if set (API rate limits).

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MODE="check"
case "${1:-}" in
    --report) MODE="report" ;;
    -h|--help) sed -n '3,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tools-openxc7-check-versions"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def ci_oss_cad_suite_version():
    """The version scripts/ci-install-oss-cad-suite.sh validates against."""
    text = open(os.path.join(repo_root, "scripts", "ci-install-oss-cad-suite.sh")).read()
    m = re.search(r'^OSS_CAD_SUITE_DATE=.*?(\d{4}-\d{2}-\d{2})', text, re.M)
    return m.group(1) if m else "?"


def apio_versions():
    """packages.<key>.release.tag from apio's remote-config (jsonc)."""
    raw = get(REMOTE_CONFIG)
    stripped = "\n".join(
        "" if ln.lstrip().startswith("//") else ln for ln in raw.splitlines()
    )
    data = json.loads(stripped)["packages"]
    return {key: data[key]["release"]["tag"] for key in ("openxc7", "oss-cad-suite")}


try:
    apio = apio_versions()
    promoted_openxc7 = json.loads(
        get("https://api.github.com/repos/FPGAwars/tools-openxc7/releases/latest")
    )["tag_name"]
    ci_ocs = ci_oss_cad_suite_version()
except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as e:
    print(f"could not resolve the published state: {e}", file=sys.stderr)
    sys.exit(0 if mode == "report" else 2)

rows = [
    # (tool, ours, ours-label, apio's remote-config tag)
    ("openxc7", promoted_openxc7, "promoted", apio["openxc7"]),
    ("oss-cad-suite", ci_ocs, "ci-validates", apio["oss-cad-suite"]),
]

print(f"{'tool':<16} {'ours':<12} {'(source)':<14} {'apio':<12} status")
drift = []
for tool, ours, label, ap in rows:
    aligned = ours == ap
    if not aligned:
        drift.append((tool, ours, label, ap))
    print(f"{tool:<16} {ours:<12} {label:<14} {ap:<12} {'OK' if aligned else 'DRIFT'}")

if not drift:
    print("\nall versions aligned")
    sys.exit(0)

print("", file=sys.stderr)
for tool, ours, label, ap in drift:
    print(f"DRIFT {tool}: {label}={ours} apio-remote-config={ap}", file=sys.stderr)
print(
    "\nopenxc7 drift: promote (or fix remote-config). oss-cad-suite drift: "
    "bump scripts/ci-install-oss-cad-suite.sh so CI validates with the same "
    "tools users get.",
    file=sys.stderr,
)
sys.exit(0 if mode == "report" else 1)
PYEOF
