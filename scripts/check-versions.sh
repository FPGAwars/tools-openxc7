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
#   oss-cad-suite  the release our CI VALIDATES the package against (the
#                  single literal OSS_CAD_SUITE_RELEASE of
#                  .github/workflows/build-pre-release.yaml)  <->  the tag of
#                  apio 1.7.x's remote-config (the line this branch builds
#                  for) -- a drift here means L1/L2 validate with different
#                  tools than users actually get. apio 1.6.x's tag is shown
#                  as well (frozen legacy line: informational, never drift)
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
    -h|--help) sed -n '3,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    "") ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
esac

python3 - "$REPO_ROOT" "$MODE" <<'PYEOF'
import json, os, re, sys, urllib.error, urllib.request

repo_root, mode = sys.argv[1], sys.argv[2]

RAW = "https://raw.githubusercontent.com/FPGAwars/apio/main/remote-config/"
# (label, url, gates): only the line this branch builds for can drift
REMOTE_CONFIGS = [
    ("apio-1.6.x", RAW + "apio-1.6.x.jsonc", False),
    ("apio-1.7.x", RAW + "apio-1.7.x.jsonc", True),
]
if os.environ.get("APIO_REMOTE_CONFIG_URL"):
    REMOTE_CONFIGS = [("override", os.environ["APIO_REMOTE_CONFIG_URL"], True)]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tools-openxc7-check-versions"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def ci_oss_cad_suite_version():
    """OSS_CAD_SUITE_RELEASE, the literal in build-pre-release.yaml."""
    path = os.path.join(repo_root, ".github", "workflows", "build-pre-release.yaml")
    text = open(path).read()
    m = re.search(r'^  OSS_CAD_SUITE_RELEASE:\s*"?(\d{4}-\d{2}-\d{2})"?', text, re.M)
    return m.group(1) if m else "?"


def apio_versions(url):
    """packages.<key>.release.tag from an apio remote-config (jsonc)."""
    raw = get(url)
    stripped = "\n".join(
        "" if ln.lstrip().startswith("//") else ln for ln in raw.splitlines()
    )
    data = json.loads(stripped)["packages"]
    return {key: data[key]["release"]["tag"] for key in ("openxc7", "oss-cad-suite")}


try:
    apio = {label: apio_versions(url) for label, url, _ in REMOTE_CONFIGS}
    promoted_openxc7 = json.loads(
        get("https://api.github.com/repos/FPGAwars/tools-openxc7/releases/latest")
    )["tag_name"]
    ci_ocs = ci_oss_cad_suite_version()
except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as e:
    print(f"could not resolve the published state: {e}", file=sys.stderr)
    sys.exit(0 if mode == "report" else 2)

if ci_ocs == "?":
    print("could not read OSS_CAD_SUITE_RELEASE from build-pre-release.yaml", file=sys.stderr)
    sys.exit(0 if mode == "report" else 2)

rows = []  # (tool, ours, ours-label, apio's tag, config label, gates)
for label, _, gates in REMOTE_CONFIGS:
    if label != "apio-1.7.x":
        # `latest` is what the 1.6.x line installs; 1.7.x moves to the new
        # release by hand at apio 1.7.0, so it is not compared with `latest`
        rows.append(("openxc7", promoted_openxc7, "promoted", apio[label]["openxc7"], label, gates))
    rows.append(("oss-cad-suite", ci_ocs, "ci-validates", apio[label]["oss-cad-suite"], label, gates))

print(f"{'tool':<16} {'ours':<12} {'(source)':<14} {'apio':<12} {'config':<12} status")
drift = []
for tool, ours, label, ap, cfg, gates in rows:
    aligned = ours == ap
    if not aligned and gates:
        drift.append((tool, ours, label, ap, cfg))
    status = "OK" if aligned else ("DRIFT" if gates else "differs (legacy line, informational)")
    print(f"{tool:<16} {ours:<12} {label:<14} {ap:<12} {cfg:<12} {status}")

if not drift:
    print("\nall versions aligned")
    sys.exit(0)

print("", file=sys.stderr)
for tool, ours, label, ap, cfg in drift:
    print(f"DRIFT {tool}: {label}={ours} {cfg}={ap}", file=sys.stderr)
print(
    "\nopenxc7 drift: make-pre-release-stable (or fix remote-config). oss-cad-suite drift: "
    "change OSS_CAD_SUITE_RELEASE in build-pre-release.yaml so CI validates with the "
    "same tools users get (see README, Bumping the oss-cad-suite).",
    file=sys.stderr,
)
sys.exit(0 if mode == "report" else 1)
PYEOF
