#!/usr/bin/env bash
# Multi-part E2E smoke over an extracted apio-openxc7 package tree.
#
#   e2e/run-parts.sh <package-dir> <workdir> [wine]
#
# For every artix7 part in chipdb-parts.json:
#   yosys (host) -> nextpnr-xilinx (--chipdb <part>.bin, generated XDC,
#   --post-route report) -> fasm2frames -> xc7frames2bit -> .bit
# With `wine`, nextpnr-xilinx.exe / xc7frames2bit.exe run under wine64
# (fasm2frames runs with the host python, as apio does on Windows via
# oss-cad-suite).
#
# Leaves <workdir>/blinky-<part>.fasm.canon (comments stripped, sorted) for
# cross-platform comparison, and requires router2 to finish and the
# --post-route report to run (parity with `apio report`).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$(cd "$1" && pwd)"
WORK="$2"
MODE="${3:-native}"
mkdir -p "$WORK"
cd "$WORK"

DB="$PKG/share/nextpnr/external/prjxray-db"
# E2E_PARTS overrides the manifest (space-separated) — handy for quick runs
PARTS=${E2E_PARTS:-$(python3 -c "import json;print(' '.join(json.load(open('$REPO/chipdb-parts.json'))['artix7']))")}

run_tool() {  # run_tool <exe-basename> <args...>
  local tool="$1"; shift
  if [ "$MODE" = wine ]; then
    wine64 "$PKG/bin/$tool.exe" "$@"
  elif [ -x "$PKG/bin/$tool" ]; then
    "$PKG/bin/$tool" "$@"
  else
    "$tool" "$@"
  fi
}

# --post-route parity probe (same idea as the windows CI E2E)
cat > report.py <<'EOF'
import json
bels = 0
for bel in ctx.getBels():
    if ctx.getBoundBelCell(bel):
        bels += 1
with open("hardware.pnr", "w") as f:
    json.dump({"bound_bels": bels}, f)
EOF

echo "== synth (host yosys, part-agnostic) =="
yosys -q -p "synth_xilinx -arch xc7 -top blinky; write_json blinky.json" \
      "$REPO/e2e/blinky.v"

fail=0
for part in $PARTS; do
  echo
  echo "===== $part ====="
  python3 "$REPO/e2e/gen_xdc.py" "$DB" artix7 "$part" > "blinky-$part.xdc"
  device=$(basename "$(ls -d "$DB/artix7/$part"-* | sort | head -1)")

  rm -f hardware.pnr
  if ! run_tool nextpnr-xilinx \
        --chipdb "$PKG/chipdb/$part.bin" \
        --xdc "blinky-$part.xdc" \
        --json blinky.json \
        --fasm "blinky-$part.fasm" \
        --post-route report.py \
        --router router2 -q; then
    echo "FAIL $part: nextpnr-xilinx (router2)"; fail=1; continue
  fi
  test -f hardware.pnr || { echo "FAIL $part: --post-route did not run"; fail=1; continue; }

  # canonical fasm: comments/whitespace stripped, sorted
  grep -v '^\s*#' "blinky-$part.fasm" | sed '/^\s*$/d' | sort > "blinky-$part.fasm.canon"

  if [ "$MODE" = wine ]; then
    PYTHONPATH="$PKG/lib/python3.12/site-packages" \
      python3 "$PKG/libexec/fasm2frames" \
        --part "$device" --db-root "$DB/artix7" "blinky-$part.fasm" \
        > "blinky-$part.frames" || { echo "FAIL $part: fasm2frames"; fail=1; continue; }
  else
    run_tool fasm2frames \
        --part "$device" --db-root "$DB/artix7" "blinky-$part.fasm" \
        > "blinky-$part.frames" || { echo "FAIL $part: fasm2frames"; fail=1; continue; }
  fi

  if ! run_tool xc7frames2bit \
        --part_file "$DB/artix7/$device/part.yaml" \
        --part_name "$device" \
        --frm_file "blinky-$part.frames" \
        --output_file "blinky-$part.bit"; then
    echo "FAIL $part: xc7frames2bit"; fail=1; continue
  fi
  test -s "blinky-$part.bit" || { echo "FAIL $part: empty .bit"; fail=1; continue; }
  echo "OK $part ($(stat -c%s "blinky-$part.bit" 2>/dev/null || stat -f%z "blinky-$part.bit") bytes)"
done

echo
if [ "$fail" -ne 0 ]; then echo "E2E: FAILURES"; exit 1; fi
echo "E2E: ALL PARTS OK"
