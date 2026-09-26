#!/usr/bin/env bash
# Multi-part E2E smoke over an extracted apio-openxc7 package tree.
#
#   e2e/run-parts.sh <package-dir> <workdir> [wine]
#
# For every part of every family in chipdb-parts.json:
#   yosys (host) -> nextpnr-xilinx (the chipdb file the package's
#   XILINX-PARTS-INDEX.json names for the part, generated XDC, --report)
#   -> fasm2frames -> xc7frames2bit -> .bit
# The place-and-route line is the one apio runs for the package's schema
# number: schema 7 and 8 (himbaechel) take the part in --device, the XDC
# and the FASM as uarch options and one chipdb per die, and route with
# router2 by default; schema 6 and 5 take --xdc/--fasm and one chipdb per
# base part, and are asked for router2.
# With `wine`, nextpnr-xilinx.exe / xc7frames2bit.exe run under wine64
# (fasm2frames runs with the host python, as apio does on Windows via
# oss-cad-suite).
#
# Leaves <workdir>/blinky-<part>.fasm.canon (comments stripped, sorted) for
# cross-platform comparison, and requires the router to finish and the
# --report JSON to carry fmax and utilization (what `apio report` reads).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$(cd "$1" && pwd)"
WORK="$2"
MODE="${3:-native}"
# wine chatters on stderr unless told not to, and that noise is not a
# fasm2frames warning. Real Windows does not need this.
if [ "$MODE" = wine ]; then
  export WINEDEBUG="${WINEDEBUG:--all}"
fi
mkdir -p "$WORK"
cd "$WORK"

DB="$PKG/share/nextpnr/external/prjxray-db"
# E2E_PARTS overrides the manifest (space-separated) — handy for quick runs
PARTS=${E2E_PARTS:-$(python3 -c "import json;print(' '.join(p for ps in json.load(open('$REPO/chipdb-parts.json')).values() for p in ps))")}

# The schema and the chipdb file of every part, from the package's own
# XILINX-PARTS-INDEX.json, the way apio reads them: a "schema <number>"
# line, then one "<part> <chipdb file>" line per part.
# shellcheck disable=SC2086
PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}" python3 -c '
import sys
from pack.parts_index import chipdb_name, read_package_schema
schema, files = read_package_schema(sys.argv[1])
print("schema", schema)
for part in sys.argv[2:]:
    print(part, files.get(part) or chipdb_name(part, schema))
' "$PKG" $PARTS > parts-chipdb.txt
SCHEMA_NUM=$(awk '$1 == "schema" {print $2}' parts-chipdb.txt)
echo "== schema: $SCHEMA_NUM =="

# part -> family, same prefix rule as pack/families.py
family_of() {
  case "$1" in
    xc7a*) echo artix7 ;;
    xc7k*) echo kintex7 ;;
    xc7s*) echo spartan7 ;;
    xc7z*) echo zynq7 ;;
    xc7v*) echo virtex7 ;;
    *) echo "unknown family for part $1" >&2; exit 1 ;;
  esac
}

run_tool() {  # run_tool <exe-basename> <args...>
  local tool="$1"; shift
  if [ "$MODE" = wine ]; then
    # The previous engine's exe embedded a python that died at
    # init_sys_streams (WinError 6) under wine when stdout was a redirected
    # FILE; the pipe costs nothing, so it stays, and stdin must be a valid
    # handle (nohup/ssh detach) -> pipe through cat, /dev/null in
    wine64 "$PKG/bin/$tool.exe" "$@" </dev/null 2>&1 | cat
  elif [ -x "$PKG/bin/$tool" ]; then
    "$PKG/bin/$tool" "$@"
  else
    "$tool" "$@"
  fi
}

if [ -n "${E2E_JSON:-}" ]; then
  # imported netlist: yosys/abc are not bit-deterministic across platforms,
  # so cross-platform fasm comparison must start from the same json
  echo "== synth skipped (using $E2E_JSON) =="
  cp "$E2E_JSON" blinky.json
else
  echo "== synth (host yosys, part-agnostic) =="
  yosys -q -p "synth_xilinx -arch xc7 -top blinky; write_json blinky.json" \
        "$REPO/e2e/blinky.v"
fi

fail=0
for part in $PARTS; do
  echo
  echo "===== $part ====="
  family=$(family_of "$part")
  chipdb=$(awk -v p="$part" '$1 == p {print $2}' parts-chipdb.txt)
  python3 "$REPO/e2e/gen_xdc.py" "$DB" "$family" "$part" > "blinky-$part.xdc"
  device=$(basename "$(ls -d "$DB/$family/$part"-* | LC_ALL=C sort | head -1)")

  rm -f "blinky-$part.pnr"
  if [ "$SCHEMA_NUM" -le 6 ]; then
    pnr=(--chipdb "$PKG/chipdb/$chipdb"
         --xdc "blinky-$part.xdc"
         --json blinky.json
         --fasm "blinky-$part.fasm"
         --report "blinky-$part.pnr"
         --router router2 -q)
  else
    pnr=(--device "$device"
         --chipdb "$PKG/chipdb/$chipdb"
         -o "xdc=blinky-$part.xdc"
         --json blinky.json
         -o "fasm=blinky-$part.fasm"
         --report "blinky-$part.pnr"
         -q)
  fi
  if ! run_tool nextpnr-xilinx "${pnr[@]}"; then
    echo "FAIL $part: nextpnr-xilinx ($chipdb)"; fail=1; continue
  fi
  # The report is what `apio report` reads: timing and utilization.
  if ! python3 - "blinky-$part.pnr" <<'PYEOF'
import json, sys
report = json.load(open(sys.argv[1]))
missing = [key for key in ("fmax", "utilization") if key not in report]
if missing or not report["utilization"]:
    raise SystemExit(f"--report lacks {missing or ['a non-empty utilization']}")
PYEOF
  then
    echo "FAIL $part: --report JSON without fmax/utilization"; fail=1; continue
  fi

  # canonical fasm: comments/whitespace stripped, sorted bytewise (the
  # locale's collation orders the same lines differently on macOS)
  # nextpnr.exe writes CRLF; drop the CR so the canon file matches the
  # other platforms line for line and byte for byte.
  grep -v '^\s*#' "blinky-$part.fasm" | sed '/^\s*$/d' | tr -d '\r' | LC_ALL=C sort > "blinky-$part.fasm.canon"

  if [ "$MODE" = wine ]; then
    # apio on real Windows runs fasm2frames with oss-cad-suite's WINDOWS
    # python and a shell redirect; emulate exactly with the mingw python
    # under wine when E2E_WINPY is set (fallback: host python)
    if [ -n "${E2E_WINPY:-}" ]; then
      # NB: under wine every std handle must be a pipe, not a file, or the
      # mingw python dies at init_sys_streams (real Windows is fine with
      # file redirects — this is a wine-only quirk)
      ( PYTHONPATH="$PKG/lib/python3.12/site-packages" \
        wine64 "$E2E_WINPY/bin/python3.exe" "$PKG/libexec/fasm2frames" \
          --part "$device" --db-root "$DB/$family" "blinky-$part.fasm" \
          </dev/null 2> >(cat > "blinky-$part.f2f.err") | cat > "blinky-$part.frames" ) \
        || { echo "FAIL $part: fasm2frames (windows python)"; tail -3 "blinky-$part.f2f.err"; fail=1; continue; }
      test -s "blinky-$part.frames" || { echo "FAIL $part: empty frames (windows python)"; tail -3 "blinky-$part.f2f.err"; fail=1; continue; }
      # Same gate as the native path: a warning is a feature the bitstream
      # does not carry. WINEDEBUG is off, so this file is fasm2frames alone.
      if [ -s "blinky-$part.f2f.err" ]; then
        echo "FAIL $part: fasm2frames said something"
        cat "blinky-$part.f2f.err"
        fail=1
        continue
      fi
    else
      PYTHONPATH="$PKG/lib/python3.12/site-packages" \
        python3 "$PKG/libexec/fasm2frames" \
          --part "$device" --db-root "$DB/$family" "blinky-$part.fasm" \
          > "blinky-$part.frames" || { echo "FAIL $part: fasm2frames"; fail=1; continue; }
    fi
  else
    run_tool fasm2frames \
        --part "$device" --db-root "$DB/$family" "blinky-$part.fasm" \
        > "blinky-$part.frames" 2> "blinky-$part.f2f.err" \
        || { echo "FAIL $part: fasm2frames"; cat "blinky-$part.f2f.err"; fail=1; continue; }
    # Every feature must have its bits: a warning here is a line of the
    # routing the bitstream does not carry.
    if [ -s "blinky-$part.f2f.err" ]; then
      echo "FAIL $part: fasm2frames said something"; cat "blinky-$part.f2f.err"; fail=1; continue
    fi
  fi

  if ! run_tool xc7frames2bit \
        --part_file "$DB/$family/$device/part.yaml" \
        --part_name "$device" \
        --frm_file "blinky-$part.frames" \
        --output_file "blinky-$part.bit"; then
    echo "FAIL $part: xc7frames2bit"; fail=1; continue
  fi
  test -s "blinky-$part.bit" || { echo "FAIL $part: empty .bit"; fail=1; continue; }
  echo "OK $part ($chipdb, $(stat -c%s "blinky-$part.bit" 2>/dev/null || stat -f%z "blinky-$part.bit") bytes)"
done

echo
if [ "$fail" -ne 0 ]; then echo "E2E: FAILURES"; exit 1; fi
echo "E2E: ALL PARTS OK"
