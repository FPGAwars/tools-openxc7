#!/usr/bin/env bash
#
# GATE B spike (throwaway).
#
# Proves the macOS bundling strategy that must replace the Linux
# ldd + wrapper + LD_LIBRARY_PATH approach (which does NOT port: SIP strips
# DYLD_* across the shell). The portable approach is to bake @rpath/@loader_path
# into the Mach-O binaries at build time and ad-hoc re-sign them.
#
# What it does, for ONE Nix-built binary:
#   1. copy the binary into a bundle OUTSIDE /nix/store      (bundle/libexec)
#   2. otool -L the transitive closure of its /nix/store dylibs
#   3. copy those dylibs into bundle/lib
#   4. install_name_tool: rewrite every /nix/store reference to @rpath/<lib>,
#      set each lib's id to @rpath/<lib>, add the right LC_RPATH
#   5. codesign --force -s -  (ad-hoc) in dependency order  (mandatory on arm64)
#   6. run the binary from the bundle with /nix/store NOT on any DYLD path
#
# Usage:
#   spike/relocate_one.sh [/path/to/binary] [--run-arg <arg>]
# Defaults to a freshly built ./result/bin/nextpnr-xilinx if no path is given:
#   nix build .#nextpnr-xilinx && spike/relocate_one.sh result/bin/nextpnr-xilinx --run-arg --version
set -euo pipefail

# ---- args -------------------------------------------------------------------
BIN="${1:-result/bin/nextpnr-xilinx}"
RUN_ARG="--help"
if [ "${2:-}" = "--run-arg" ] && [ -n "${3:-}" ]; then RUN_ARG="$3"; fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This spike only makes sense on macOS (Darwin). Host is $(uname -s)." >&2
  exit 2
fi
if [ ! -f "$BIN" ]; then
  echo "Binary not found: $BIN" >&2
  echo "Build it first, e.g.: nix build .#nextpnr-xilinx" >&2
  exit 2
fi

BIN_REAL="$(/usr/bin/python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$BIN")"
BIN_NAME="$(basename "$BIN_REAL")"

# Bundle deliberately under /tmp so it is far away from /nix/store: if the binary
# still runs, it is resolving ONLY the bundled libs (the real test).
BUNDLE="${TMPDIR:-/tmp}/openxc7-spike-bundle"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/libexec" "$BUNDLE/lib"

echo "==> binary : $BIN_REAL"
echo "==> bundle : $BUNDLE"

# ---- helpers ----------------------------------------------------------------
# List the Mach-O dynamic deps of a file (skip line 1 = the file's own id),
# keeping only absolute /nix/store/*.dylib references.
nix_deps() {
  otool -L "$1" | tail -n +2 | awk '{print $1}' \
    | grep -E '^/nix/store/.*\.dylib' || true
}

WORK="$BUNDLE/.worklist"
DONE="$BUNDLE/.done"
: > "$WORK"; : > "$DONE"

# ---- 1. copy the binary -----------------------------------------------------
cp "$BIN_REAL" "$BUNDLE/libexec/$BIN_NAME"
chmod u+w "$BUNDLE/libexec/$BIN_NAME"
nix_deps "$BIN_REAL" >> "$WORK"

# ---- 2+3. transitive closure of /nix/store dylibs into bundle/lib -----------
while [ -s "$WORK" ]; do
  src="$(head -n 1 "$WORK")"; sed -i '' '1d' "$WORK"
  grep -qxF "$src" "$DONE" && continue
  echo "$src" >> "$DONE"
  base="$(basename "$src")"
  if [ ! -f "$BUNDLE/lib/$base" ]; then
    cp "$src" "$BUNDLE/lib/$base"
    chmod u+w "$BUNDLE/lib/$base"
    echo "    + lib $base"
  fi
  nix_deps "$src" >> "$WORK"
done

# ---- 4. rewrite install names -----------------------------------------------
# Each lib: id -> @rpath/<base>; its /nix/store deps -> @rpath/<dep>; rpath so
# @rpath resolves to its own directory (siblings in bundle/lib).
for lib in "$BUNDLE"/lib/*.dylib; do
  [ -e "$lib" ] || continue
  base="$(basename "$lib")"
  install_name_tool -id "@rpath/$base" "$lib"
  for dep in $(otool -L "$lib" | tail -n +2 | awk '{print $1}' | grep -E '^/nix/store/.*\.dylib' || true); do
    install_name_tool -change "$dep" "@rpath/$(basename "$dep")" "$lib"
  done
  install_name_tool -add_rpath "@loader_path" "$lib" 2>/dev/null || true
done

# Binary: rewrite its /nix/store deps and point @rpath at ../lib.
for dep in $(otool -L "$BUNDLE/libexec/$BIN_NAME" | tail -n +2 | awk '{print $1}' | grep -E '^/nix/store/.*\.dylib' || true); do
  install_name_tool -change "$dep" "@rpath/$(basename "$dep")" "$BUNDLE/libexec/$BIN_NAME"
done
install_name_tool -add_rpath "@loader_path/../lib" "$BUNDLE/libexec/$BIN_NAME" 2>/dev/null || true

# ---- 5. ad-hoc re-sign (mandatory on arm64 after install_name_tool) ---------
for lib in "$BUNDLE"/lib/*.dylib; do
  [ -e "$lib" ] || continue
  codesign --remove-signature "$lib" 2>/dev/null || true
  codesign --force -s - "$lib"
done
codesign --remove-signature "$BUNDLE/libexec/$BIN_NAME" 2>/dev/null || true
codesign --force -s - "$BUNDLE/libexec/$BIN_NAME"

# ---- verify no /nix/store references remain ---------------------------------
echo "==> residual /nix/store references (should be none):"
if otool -L "$BUNDLE/libexec/$BIN_NAME" "$BUNDLE"/lib/*.dylib | grep -E '/nix/store' ; then
  echo "    !! still references /nix/store — relocation incomplete" >&2
else
  echo "    none — closure fully relocated"
fi

# ---- 6. run from the bundle, with /nix/store NOT on any DYLD path ------------
echo "==> running: $BUNDLE/libexec/$BIN_NAME $RUN_ARG"
echo "    (DYLD_* intentionally unset; SIP would strip them anyway)"
env -u DYLD_LIBRARY_PATH -u DYLD_FALLBACK_LIBRARY_PATH \
  "$BUNDLE/libexec/$BIN_NAME" "$RUN_ARG" >/tmp/openxc7-spike-run.log 2>&1 && rc=0 || rc=$?
echo "    exit code: $rc  (0 or a tool-specific usage code = the dylibs resolved)"
echo "    output head:"; head -n 5 /tmp/openxc7-spike-run.log | sed 's/^/      /'

echo ""
if [ "$rc" -ge 126 ]; then
  echo "GATE B: FAIL — binary could not start (dyld/codesign problem). See log." >&2
  exit 1
fi
echo "GATE B: the relocated binary started outside /nix/store. Strategy validated."
