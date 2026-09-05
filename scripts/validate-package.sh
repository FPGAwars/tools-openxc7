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
#   --chipdb-dir DIR       directory of chipdb .bin the package does not ship
#   --parts "<p1 p2 ...>"  restrict the E2E to these parts (E2E_PARTS)
#   --expect-date YYYYMMDD assert the package is dated with this id
#   --skip-e2e             layout/marker/version checks only (fast)
#   --keep                 keep the scratch directory for inspection
#
# A released package ships NO chipdb: chipdb/ holds only the placeholder
# README.txt and apio downloads the .bin its board needs from the release
# assets. Validating one therefore needs --chipdb-dir (in CI, the same
# chipdb-bins artifact the release assets were built from): the bins are
# checked against XILINX-PARTS-INDEX.json and then INJECTED into the
# extracted package, exactly where and how apio leaves them, before the
# E2E runs. A
# package that does ship its chipdb (the local full pack) is validated as
# it stands, with no --chipdb-dir.
#
# Checks: package layout, chipdb completeness vs chipdb-parts.json,
# XILINX-PARTS-INDEX.json and its agreement with the bins it describes,
# feature markers inside the packaged nextpnr binary, --version == the rev recorded
# in nix/, platform extras on darwin (ad-hoc codesign + zero residual
# /nix/store references), and the multi-part E2E (e2e/run-parts.sh) against
# the extracted package.
#
# Requirements: yosys + python3 on PATH for the E2E (per the reproducibility
# norm, from the required oss-cad-suite version); wine64 on PATH for --wine.
# Exit code != 0 means the package is INVALID.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RESET=$'\033[0m'
fail() { printf '%s❌ %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }
ok()   { printf '%s✅ %s%s\n' "$GREEN" "$*" "$RESET"; }
note() { printf '%s—  %s%s\n' "$YELLOW" "$*" "$RESET"; }

PKG_IN="" WINE=0 PARTS="" EXPECT_DATE="" KEEP=0 SKIP_E2E=0 CHIPDB_DIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --wine) WINE=1 ;;
        --chipdb-dir) CHIPDB_DIR="$2"; shift ;;
        --parts) PARTS="$2"; shift ;;
        --expect-date) EXPECT_DATE="$2"; shift ;;
        --skip-e2e) SKIP_E2E=1 ;;
        --keep) KEEP=1 ;;
        -h|--help) sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) fail "unknown option: $1" ;;
        *) [ -z "$PKG_IN" ] && PKG_IN="$1" || fail "unexpected argument: $1" ;;
    esac
    shift
done
[ -n "$PKG_IN" ] || fail "usage: validate-package.sh <package.tgz|dir> [--wine] [--chipdb-dir DIR] [--parts \"...\"]"
if [ -n "$CHIPDB_DIR" ]; then
    [ -d "$CHIPDB_DIR" ] || fail "no such chipdb directory: $CHIPDB_DIR"
    CHIPDB_DIR=$(cd "$CHIPDB_DIR" && pwd)
fi

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

# --- chipdb: shipped with the package, or downloaded on demand? -------------
# A released package carries only chipdb/README.txt: apio downloads the .bin
# its board needs from the release assets. Everything that needs a real
# chipdb -- the E2E below, the regression suite, the user -- gets it from
# --chipdb-dir, injected here exactly where apio leaves it.
ON_DEMAND=0
if [ -z "$(find "$PKG/chipdb" -maxdepth 1 -name '*.bin' -print -quit 2>/dev/null)" ]; then
    ON_DEMAND=1
fi
if [ "$ON_DEMAND" = 1 ]; then
    [ -f "$PKG/chipdb/README.txt" ] \
        || fail "chipdb/ has neither bins nor the on-demand README.txt placeholder"
    STRAY=$(cd "$PKG/chipdb" && ls -A | grep -vx 'README.txt' | tr '\n' ' ' || true)
    [ -z "$STRAY" ] || fail "chipdb/ must hold README.txt only, it also has: $STRAY"
    [ -n "$CHIPDB_DIR" ] \
        || fail "this package ships no chipdb: pass --chipdb-dir <dir with the release bins>"
    note "on-demand chipdb: chipdb/ holds only README.txt; bins from $CHIPDB_DIR"
    if [ -z "$TARBALL" ]; then
        # A directory the caller owns: validate a copy of it, so the
        # injection never leaves 1.1 GB of bins in someone else's tree.
        cp -a "$PKG" "$SCRATCH/pkg"
        PKG="$SCRATCH/pkg"
        note "directory package copied into the scratch tree before injection"
    fi
    CHIPDB_SRC="$CHIPDB_DIR"
else
    [ -z "$CHIPDB_DIR" ] || note "--chipdb-dir ignored: this package ships its own chipdb"
    CHIPDB_SRC="$PKG/chipdb"
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
    [ -f "$CHIPDB_SRC/$part.bin" ] || fail "chipdb missing: $CHIPDB_SRC/$part.bin"
    # each family's prjxray-db must travel with its parts (fasm2frames needs
    # the segbits + part.yaml of that family), on-demand chipdb or not
    [ -d "$PKG/share/nextpnr/external/prjxray-db/$family" ]         || fail "prjxray-db missing for family: $family"
    NPARTS=$((NPARTS + 1))
done < "$SCRATCH/parts.txt"
ok "chipdb: all $NPARTS manifest parts present (with their family dbs)"

# --- XILINX-PARTS-INDEX.json, and the chipdb files it describes ----------
INDEX="$PKG/XILINX-PARTS-INDEX.json"
[ -f "$INDEX" ] || fail "XILINX-PARTS-INDEX.json missing from package root"
if PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m pack.parts_index "$INDEX" "$CHIPDB_SRC"
then
    ok "XILINX-PARTS-INDEX.json: valid schema, and every chipdb file matches what it records"
else
    fail "XILINX-PARTS-INDEX.json invalid"
fi
# The index names the assets by the release date. If it disagreed with
# the package, apio would fetch chipdb files from another release (a run
# crossing midnight UTC is how that happens).
if [ -n "$EXPECT_DATE" ]; then
    INDEX_DATE=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['date'])" "$INDEX")
    [ "$INDEX_DATE" = "$EXPECT_DATE" ] \
        || fail "XILINX-PARTS-INDEX.json is dated $INDEX_DATE, the package $EXPECT_DATE"
    ok "XILINX-PARTS-INDEX.json dated $EXPECT_DATE, like the package"
fi

# --- inject the on-demand bins, the way apio does ---------------------------
if [ "$ON_DEMAND" = 1 ]; then
    cp "$CHIPDB_SRC"/*.bin "$PKG/chipdb/"
    INJECTED=$(find "$PKG/chipdb" -maxdepth 1 -name '*.bin' | wc -l | tr -d ' ')
    [ "$INJECTED" = "$NPARTS" ] || fail "injected $INJECTED bins, expected $NPARTS"
    ok "chipdb injected: $INJECTED bins in chipdb/, where apio leaves them"
fi

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

# --- --version must be the expected rev ---------------------------------------
EXPECTED_REV=$(sed -n 's/.*rev = "\([0-9a-f]\{40\}\)".*/\1/p' "$REPO_ROOT/nix/nextpnr-xilinx.nix" | head -1)
[ -n "$EXPECTED_REV" ] || fail "cannot parse the expected nextpnr rev from nix/nextpnr-xilinx.nix"
if [ "$WINE" = 1 ]; then
    VOUT=$(WINEDEBUG=-all wine64 "$NEXTPNR_BIN" --version </dev/null 2>&1 || true)
else
    VOUT=$("$PKG/bin/nextpnr-xilinx" --version 2>&1 || true)
fi
# The nix build stamps the SHORT rev (7 hex chars) into --version.
if printf '%s' "$VOUT" | grep -q "${EXPECTED_REV:0:7}"; then
    ok "--version matches the expected rev (${EXPECTED_REV:0:7})"
else
    printf '%s\n' "$VOUT" | head -5 >&2
    fail "--version does not contain the expected rev ${EXPECTED_REV:0:7}"
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
    command -v yosys >/dev/null 2>&1 || fail "yosys not on PATH (install the required oss-cad-suite version)"
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
