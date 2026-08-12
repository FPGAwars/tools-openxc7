#!/usr/bin/env bash
#
# validate-package.sh -- the L1 release gate: validate an openXC7 package
# INSIDE its tarball (never the freshly built store tree -- a packer reusing
# a stale dist/ is exactly the failure mode this catches).
#
# Usage:
#   scripts/validate-package.sh <package.tgz|package-dir> [options]
#
# Options:
#   --wine                 the package is windows-amd64; run it under wine64
#   --parts "<p1 p2 ...>"  restrict the E2E to these parts (E2E_PARTS)
#   --expect-date YYYYMMDD assert the package is dated with this id
#   --skip-e2e             layout/marker/version checks only (fast)
#   --keep                 keep the scratch directory for inspection
#
# Checks: package layout, chipdb completeness vs chipdb-parts.json, feature
# markers inside the packaged nextpnr binary, --version == the rev pinned in
# nix/, platform extras on darwin (ad-hoc codesign + zero residual /nix/store
# references), and the multi-part E2E (e2e/run-parts.sh) against the
# extracted package.
#
# Requirements: yosys + python3 on PATH for the E2E (per the reproducibility
# norm, from the pinned oss-cad-suite); wine64 on PATH for --wine.
# Exit code != 0 means the package is INVALID.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RESET=$'\033[0m'
fail() { printf '%s❌ %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }
ok()   { printf '%s✅ %s%s\n' "$GREEN" "$*" "$RESET"; }
note() { printf '%s—  %s%s\n' "$YELLOW" "$*" "$RESET"; }

PKG_IN="" WINE=0 PARTS="" EXPECT_DATE="" KEEP=0 SKIP_E2E=0
while [ $# -gt 0 ]; do
    case "$1" in
        --wine) WINE=1 ;;
        --parts) PARTS="$2"; shift ;;
        --expect-date) EXPECT_DATE="$2"; shift ;;
        --skip-e2e) SKIP_E2E=1 ;;
        --keep) KEEP=1 ;;
        -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) fail "unknown option: $1" ;;
        *) [ -z "$PKG_IN" ] && PKG_IN="$1" || fail "unexpected argument: $1" ;;
    esac
    shift
done
[ -n "$PKG_IN" ] || fail "usage: validate-package.sh <package.tgz|dir> [--wine] [--parts \"...\"]"

SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/openxc7-validate.XXXXXX")
cleanup() {
    if [ "$KEEP" = 1 ]; then note "scratch kept at: $SCRATCH"; else rm -rf "$SCRATCH"; fi
}
trap cleanup EXIT

# --- unpack (or take a directory) ------------------------------------------
TARBALL=""
if [ -d "$PKG_IN" ]; then
    PKG=$(cd "$PKG_IN" && pwd)
    note "validating a directory tree (no tarball-level checks)"
else
    [ -f "$PKG_IN" ] || fail "no such package: $PKG_IN"
    TARBALL=$(cd "$(dirname "$PKG_IN")" && pwd)/$(basename "$PKG_IN")
    mkdir -p "$SCRATCH/pkg"
    tar xzf "$TARBALL" -C "$SCRATCH/pkg" || fail "cannot extract $TARBALL"
    PKG="$SCRATCH/pkg"
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$TARBALL"
    else shasum -a 256 "$TARBALL"; fi
fi

# --- identify the package platform -----------------------------------------
HOST=$(uname -s)
if [ -f "$PKG/bin/nextpnr-xilinx.exe" ]; then
    PLAT="windows-amd64"
    NEXTPNR_BIN="$PKG/bin/nextpnr-xilinx.exe"
    [ "$WINE" = 1 ] || fail "windows package: pass --wine (validation runs under wine64)"
    command -v wine64 >/dev/null 2>&1 || fail "wine64 not on PATH"
elif [ -f "$PKG/libexec/nextpnr-xilinx" ]; then
    case "$HOST" in
        Darwin) PLAT="darwin-arm64" ;;
        Linux)  PLAT="linux-x86-64" ;;
        *) fail "unsupported host: $HOST" ;;
    esac
    NEXTPNR_BIN="$PKG/libexec/nextpnr-xilinx"
    [ "$WINE" = 0 ] || fail "--wine given but this is not a windows package"
else
    fail "unrecognized layout: no bin/nextpnr-xilinx.exe nor libexec/nextpnr-xilinx"
fi
note "package platform: $PLAT"

# A native package must match the host (windows validates under wine anywhere
# with wine64; a linux tarball cannot be validated on darwin or vice versa).
if [ -n "$TARBALL" ]; then
    base=$(basename "$TARBALL")
    case "$base" in
        apio-openxc7-"$PLAT"-*.tgz) : ;;
        apio-openxc7-*) fail "tarball name ($base) does not match detected platform ($PLAT)" ;;
        *) note "non-canonical tarball name: $base" ;;
    esac
    if [ -n "$EXPECT_DATE" ]; then
        case "$base" in
            *"-$EXPECT_DATE.tgz") ok "tarball dated $EXPECT_DATE" ;;
            *) fail "tarball $base is not dated $EXPECT_DATE (apio derives the date from the release TAG)" ;;
        esac
    fi
fi

# --- BUILD-INFO.json (ecosystem convention) ---------------------------------
if [ -f "$PKG/BUILD-INFO.json" ]; then
    if python3 - "$PKG/BUILD-INFO.json" "$PLAT" <<'PYEOF'
import json, sys
info = json.load(open(sys.argv[1]))
plat = info.get("target-platform")
if plat != sys.argv[2]:
    raise SystemExit(f"target-platform {plat!r} != {sys.argv[2]!r}")
for key in ("package-name", "release-tag", "yosys-release-tag"):
    if not info.get(key):
        raise SystemExit(f"missing field: {key}")
PYEOF
    then ok "BUILD-INFO.json present and coherent"
    else fail "BUILD-INFO.json invalid (bad JSON, platform mismatch or missing fields)"
    fi
else
    note "BUILD-INFO.json missing (pre-convention package)"
fi

# --- chipdb completeness vs the manifest ------------------------------------
python3 - "$REPO_ROOT/chipdb-parts.json" > "$SCRATCH/parts.txt" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    manifest = json.load(f)
for family, parts in manifest.items():
    for part in parts:
        print(f"{family} {part}")
PYEOF
[ -s "$SCRATCH/parts.txt" ] || fail "empty part list from chipdb-parts.json"
NPARTS=0
while read -r family part; do
    [ -f "$PKG/chipdb/$part.bin" ] || fail "chipdb missing: chipdb/$part.bin"
    # each family's prjxray-db must travel with its parts (fasm2frames needs
    # the segbits + part.yaml of that family)
    [ -d "$PKG/share/nextpnr/external/prjxray-db/$family" ]         || fail "prjxray-db missing for family: $family"
    NPARTS=$((NPARTS + 1))
done < "$SCRATCH/parts.txt"
ok "chipdb: all $NPARTS manifest parts present (with their family dbs)"

# --- bundled tools ----------------------------------------------------------
if [ "$PLAT" = "windows-amd64" ]; then
    # bare shebang scripts do not launch from CMD/PowerShell (apio#914):
    # windows ships libexec/ + a .cmd launcher, like fasm2frames
    [ -f "$PKG/bin/xc7pll.cmd" ]   || fail "xc7pll.cmd launcher missing from bin/"
    [ -f "$PKG/libexec/xc7pll" ]   || fail "xc7pll missing from libexec/"
    # fasm's antlr-fallback RuntimeWarning must be silenced (apio#913):
    # textX is the intended parser on windows, imported directly
    grep -q "INTENDED parser" "$PKG/lib/python3.12/site-packages/fasm/parser/__init__.py" \
        || fail "fasm parser __init__ not patched (apio#913 warning would fire)"
    PLL_OUT=$(python3 "$PKG/libexec/xc7pll" -i 100 -o 65 --report 2>&1) || fail "xc7pll does not run: $PLL_OUT"
else
    [ -f "$PKG/bin/xc7pll" ]       || fail "xc7pll missing from bin/"
    PLL_OUT=$(python3 "$PKG/bin/xc7pll" -i 100 -o 65 --report 2>&1) || fail "xc7pll does not run: $PLL_OUT"
fi
echo "$PLL_OUT" | grep -q "CLKFBOUT_MULT:    13"         || fail "xc7pll produced unexpected output"
# module output is the DEFAULT since 1.1.0 (apio#915, parity with ecppll)
if echo "$PLL_OUT" | grep -q "PLLE2_BASE"; then
    fail "xc7pll --report unexpectedly emitted a module"
fi
ok "xc7pll: present and functional"

# --- feature markers inside the packaged binary -----------------------------
MARKERS=$(grep -a -c reportClockFmaxJson "$NEXTPNR_BIN" || true)
[ "${MARKERS:-0}" -ge 1 ] || fail "marker reportClockFmaxJson NOT in the packaged nextpnr (stale binary?)"
ok "markers: reportClockFmaxJson present in the packaged binary"

# --- --version must be the pinned rev ---------------------------------------
PINNED=$(sed -n 's/.*rev = "\([0-9a-f]\{40\}\)".*/\1/p' "$REPO_ROOT/nix/nextpnr-xilinx.nix" | head -1)
[ -n "$PINNED" ] || fail "cannot parse the pinned nextpnr rev from nix/nextpnr-xilinx.nix"
if [ "$WINE" = 1 ]; then
    VOUT=$(WINEDEBUG=-all wine64 "$NEXTPNR_BIN" --version </dev/null 2>&1 || true)
else
    VOUT=$("$PKG/bin/nextpnr-xilinx" --version 2>&1 || true)
fi
# The nix build stamps the SHORT rev (7 hex chars) into --version.
if printf '%s' "$VOUT" | grep -q "${PINNED:0:7}"; then
    ok "--version matches the pinned rev (${PINNED:0:7})"
else
    printf '%s\n' "$VOUT" | head -5 >&2
    fail "--version does not contain the pinned rev ${PINNED:0:7}"
fi

# --- darwin extras: codesign + no residual /nix/store refs ------------------
if [ "$PLAT" = "darwin-arm64" ]; then
    codesign -v "$NEXTPNR_BIN" 2>&1 || fail "codesign invalid: $NEXTPNR_BIN"
    BADSIG=0
    while IFS= read -r dylib; do
        codesign -v "$dylib" 2>/dev/null || { echo "codesign invalid: $dylib" >&2; BADSIG=1; }
    done < <(find "$PKG/lib" -maxdepth 1 -name '*.dylib' 2>/dev/null)
    [ "$BADSIG" = 0 ] || fail "unsigned/invalid dylibs in lib/ (arm64 requires ad-hoc signatures)"
    ok "codesign: nextpnr + lib/*.dylib verify"
    # Relocation check: the Mach-O LOAD COMMANDS (linked dylibs + rpaths)
    # must never point at /nix/store. Inert strings inside binaries or stale
    # shebang lines in libexec python scripts are expected and harmless (the
    # scripts are always invoked via an explicit python).
    BAD=0
    while IFS= read -r f; do
        file -b "$f" | grep -q 'Mach-O' || continue
        if otool -L "$f" 2>/dev/null | grep -q '/nix/store' || \
           otool -l "$f" 2>/dev/null | grep -A2 LC_RPATH | grep -q '/nix/store'; then
            echo "store-linked: $f" >&2
            BAD=1
        fi
    done < <({ find "$PKG/bin" "$PKG/libexec" "$PKG/lib" -maxdepth 1 -type f
               find "$PKG/lib" -name '*.so' -o -name '*.dylib'; } 2>/dev/null | sort -u)
    [ "$BAD" = 0 ] || fail "Mach-O load commands still reference /nix/store (relocation incomplete)"
    ok "relocation: no /nix/store in any Mach-O load command"
fi

# --- E2E: the real bar -------------------------------------------------------
if [ "$SKIP_E2E" = 1 ]; then
    note "E2E SKIPPED (--skip-e2e): this does NOT meet the release bar"
else
    command -v yosys >/dev/null 2>&1 || fail "yosys not on PATH (install the pinned oss-cad-suite)"
    WORK="$SCRATCH/e2e"
    if [ -n "$PARTS" ]; then
        export E2E_PARTS="$PARTS"
        note "E2E restricted to: $PARTS"
    fi
    if [ "$WINE" = 1 ]; then
        bash "$REPO_ROOT/e2e/run-parts.sh" "$PKG" "$WORK" wine
    else
        bash "$REPO_ROOT/e2e/run-parts.sh" "$PKG" "$WORK"
    fi
    ok "E2E passed"
fi

ok "PACKAGE VALID: $PLAT${TARBALL:+ ($(basename "$TARBALL"))}"
