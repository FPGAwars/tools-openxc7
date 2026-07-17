# Reproducible assembly of the apio-openxc7-windows-amd64 package, cross-built
# from x86_64-linux with pkgsCross.mingwW64. Build with:
#   nix build .#packages.x86_64-linux.openxc7-windows-amd64
#
# Full feature parity with Linux/macOS: nextpnr-xilinx.exe embeds a Python
# interpreter (boost::python), so apio's `--post-route` report (apio report)
# works on Windows too.
#
# The result ($out) is the package TREE; the dated .tgz is produced by CI
# (.github/workflows/windows-package.yml). Reuses the flake's native
# derivations for the platform-independent parts (chipdb .bin, prjxray-db data,
# fasm/prjxray python). Only the native .exe come from the mingw cross here.
{ pkgs
, lib
, nextpnr-xilinx           # native: provides share/ data
, prjxray                  # native: provides prjxray python + fasm2frames/bit2fasm
, fasm                     # native python package (pulls textx -> arpeggio)
, nextpnr-xilinx-chipdb    # native: artix7 chipdb (every footprint's .bin)
, utilPatch ? null         # store/util.py (prjxray flock workaround), optional
}:

let
  # mingw cross set, re-imported with allowUnsupportedSystem so the conservative
  # meta.platforms of header-only deps (eigen) don't block the cross eval.
  cross = import pkgs.path {
    localSystem = pkgs.system;
    crossSystem = pkgs.lib.systems.examples.mingwW64;
    config.allowUnsupportedSystem = true;
  };
  python      = pkgs.python3;       # native interpreter, runs build-time scripts
  # Python EMBEDDED in nextpnr-xilinx.exe. 3.11, not 3.12: the mingw cross of
  # cpython 3.12 is broken in this nixpkgs (its patch targets distutils, removed
  # in 3.12). This interpreter is independent of the fasm tools' python and only
  # needs the stdlib (json/os/pathlib) for the report script.
  mingwPython = cross.python311;

  # -- pinned sources (same revs/hashes as nix/nextpnr-xilinx.nix, nix/prjxray.nix)
  nextpnrSrc = pkgs.fetchFromGitHub {
    owner = "openXC7"; repo = "nextpnr-xilinx";
    rev = "3374e5a62b54dc346fd5f85188ed24075ddfd5fb";
    hash = "sha256-gW3Z3Cd5/gfX7k/ekRHtPVlbhKszWah1L+HggMFKakA=";
    fetchSubmodules = true;
  };
  prjxraySrc = pkgs.fetchFromGitHub {
    owner = "f4pga"; repo = "prjxray";
    rev = "bdbc665852b82f589ff775a8f6498542dbec0a07";
    hash = "sha256-lV4o62lS7CMG0EYPhp9bTB4fg0hOixy8CC8yGxKhGQE=";
    fetchSubmodules = true;
  };

  commonFlags = [
    "-DARCH=xilinx" "-DBUILD_GUI=OFF" "-DBUILD_TESTS=OFF" "-DUSE_OPENMP=OFF"
    "-Wno-deprecated" "-DCURRENT_GIT_VERSION=3374e5a"
    "-DPython3_EXECUTABLE=${python.interpreter}"
  ];

  # boost WITH python (nextpnr's embedded interpreter) + mingw pthreads (boost::
  # python's headers include <pthread.h>) + without zstd (zstd-mingw -> gnugrep
  # -> bash-mingw doesn't cross). Used by both nextpnr and prjxray (one build).
  boostPy = (cross.boost.override { enablePython = true; python = mingwPython; })
    .overrideAttrs (o: {
      buildInputs =
        (builtins.filter (x: !(lib.hasInfix "zstd" (x.name or ""))) (o.buildInputs or []))
        ++ [ cross.windows.mingw_w64_pthreads ];
    });

  # nextpnr two-stage cross: native bbasm -> ImportExecutables.cmake -> cross import
  bba = pkgs.stdenv.mkDerivation {
    pname = "nextpnr-xilinx-bbasm-native"; version = "0.8.2";
    src = nextpnrSrc;
    nativeBuildInputs = [ pkgs.cmake pkgs.git python ];
    buildInputs = [ pkgs.boost pkgs.eigen ];
    cmakeFlags = commonFlags ++ [ "-DBUILD_PYTHON=OFF" ];
    buildFlags = [ "bbasm" ];
    installPhase = ''
      mkdir -p $out/bin
      cp bbasm $out/bin/
      sed "s|IMPORTED_LOCATION \"[^\"]*\"|IMPORTED_LOCATION \"$out/bin/bbasm\"|" \
        ImportExecutables.cmake > $out/ImportExecutables.cmake
    '';
  };

  nextpnrWin = cross.stdenv.mkDerivation {
    pname = "nextpnr-xilinx-win"; version = "0.8.2";
    src = nextpnrSrc;
    # The SAME nextpnr patch list as nix/nextpnr-xilinx.nix: the .exe must
    # behave like the native binaries. (The chipdb .bin are NOT built here —
    # they come prebuilt from the native chipdb derivation — so the bbaexport
    # patch is inert here; it is included to keep one canonical list.)
    # Gap found 2026-07-15: the 20260716 windows exe shipped without
    # xdc-virtual-clock-crash.patch because this list was missing.
    patches = [
      ../patches/bbaexport-global-const-node.patch
      ../patches/xdc-virtual-clock-crash.patch
      ../patches/timing-fmax-python.patch
      ../patches/frontend-hier-merge-nets.patch
    ];
    nativeBuildInputs = [ pkgs.cmake pkgs.git python ];
    buildInputs = [ boostPy cross.eigen cross.windows.mingw_w64_pthreads mingwPython ];
    enableParallelBuilding = true;
    postPatch = ''
      # router2: boost::container::flat_map's sorted invariant breaks on mingw
      # (count() true but at() throws) -> std::map. No change on Linux. Upstream PR.
      sed -i 's|boost::container::flat_map<int, std::pair<int, PipId>> bound_nets;|std::map<int, std::pair<int, PipId>> bound_nets;|' common/router2.cc
      grep -q '#include <map>' common/router2.cc || \
        sed -i 's|#include <boost/container/flat_map.hpp>|#include <boost/container/flat_map.hpp>\n#include <map>|' common/router2.cc
      # getPipName/getWireName copy whole chipdb PODs by value; the last record
      # of the file then reads a few bytes past the mapping end -> page fault
      # under the Windows file mapping (benign-but-UB on Linux, found by
      # ASan/UBSan with a clocked design). const refs only read real fields.
      # Upstream PR material.
      sed -i 's|auto loc_info  = locInfo(pip);|const auto \&loc_info  = locInfo(pip);|' xilinx/arch.cc
      sed -i 's|auto pip_data  = loc_info.pip_data\[pip.index\];|const auto \&pip_data  = loc_info.pip_data[pip.index];|' xilinx/arch.cc
      sed -i 's|auto tile_inst = chip_info->tile_insts\[pip.tile\];|const auto \&tile_inst = chip_info->tile_insts[pip.tile];|' xilinx/arch.cc
      sed -i 's|auto wire_data = locInfo(w).wire_data\[w.index\];|const auto \&wire_data = locInfo(w).wire_data[w.index];|' xilinx/arch.cc
      grep -q "const auto &pip_data" xilinx/arch.cc || { echo "POD-ref patch failed"; exit 1; }
      # nixpkgs names the boost python lib 'python' (no version suffix); add "" to
      # the version search list so find_package(Boost COMPONENTS python) matches.
      sed -i 's|foreach (PyVer 3 36 37 38 39 310 311 312)|foreach (PyVer "" 3 36 37 38 39 310 311 312)|' CMakeLists.txt
      # boost::python is a static .a here (not a DLL) -> define BOOST_PYTHON_STATIC_LIB
      # so the headers don't use dllimport (__imp_ undefined references at link).
      sed -i 's|    # Find Boost::Python of a suitable version in a cross-platform way|    add_definitions(-DBOOST_PYTHON_STATIC_LIB)\n    # Find Boost::Python of a suitable version in a cross-platform way|' CMakeLists.txt
    '';
    cmakeFlags = commonFlags ++ [
      "-DBUILD_PYTHON=ON"
      "-DIMPORT_EXECUTABLES=${bba}/ImportExecutables.cmake"
      # cross find_package(Python3 Development): point at the target (mingw) python
      "-DPython3_INCLUDE_DIR=${mingwPython}/include/python3.11"
      "-DPython3_LIBRARY=${mingwPython}/lib/python3.11/config-3.11/libpython3.11.dll.a"
    ];
    installPhase = ''
      mkdir -p $out/bin
      cp *.exe $out/bin/
      test -f $out/bin/nextpnr-xilinx.exe
    '';
    dontStrip = true;
  };

  prjxrayWin = cross.stdenv.mkDerivation {
    pname = "prjxray-win"; version = "bdbc665";
    src = prjxraySrc;
    nativeBuildInputs = [ pkgs.cmake pkgs.git python ];
    buildInputs = [ boostPy cross.eigen cross.windows.mingw_w64_pthreads ];
    enableParallelBuilding = true;
    # POSIX -> Win32 ports (#ifdef _WIN32; Linux path unchanged) + the deprecated
    # warning suppression from nix/prjxray.nix.
    postPatch = ''
      cp ${./prjxray-patches/memory_mapped_file.cc} lib/memory_mapped_file.cc
      cp ${./prjxray-patches/database.cc} lib/database.cc
      sed -i '29 itarget_compile_options(libprjxray PUBLIC "-Wno-deprecated")' lib/CMakeLists.txt || true
    '';
    cmakeFlags = [
      "-DCMAKE_BUILD_TYPE=Release" "-Wno-deprecated"
      "-DPython3_EXECUTABLE=${python.interpreter}"
      # mingw explicit-template-instantiation duplicate (Configuration<Spartan6>)
      "-DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-multiple-definition"
    ];
    installPhase = ''
      mkdir -p $out/bin
      for t in xc7frames2bit bitread xc7patch; do
        cp "$(find . -name "$t.exe" | head -1)" $out/bin/
      done
      test -f $out/bin/xc7frames2bit.exe
    '';
    dontStrip = true;
  };

  # parts to ship, from the shared manifest (same list as openxc7-pack.py)
  chipdbParts = (builtins.fromJSON (builtins.readFile ../../chipdb-parts.json)).artix7;

  # build only the manifest parts (the full artix7 family would also build
  # seven more GB-class xc7a200t package variants we don't ship)
  chipdb = nextpnr-xilinx-chipdb.artix7.override { parts = chipdbParts; };
  gccLib = "${cross.stdenv.cc.cc.lib}/x86_64-w64-mingw32/lib";

  # pure-python tool env (fasm pulls textx -> arpeggio; + prjxray's python deps).
  # withPackages keeps the *.dist-info metadata (textX needs version("textx")).
  # This is the TOOLS python (3.12), separate from nextpnr's embedded 3.11.
  pyEnv = python.withPackages (ps: [
    fasm ps.simplejson ps.intervaltree ps.sortedcontainers ps.pyyaml
  ]);

  cmdLauncher = name: ''
    printf '@echo off\r\nset "PKG=%%~dp0.."\r\nset "PYTHONPATH=%%PKG%%\\lib\\python3.12\\site-packages;%%PYTHONPATH%%"\r\npython "%%PKG%%\\libexec\\${name}" %%*\r\n' > $out/bin/${name}.cmd
  '';

in pkgs.runCommand "apio-openxc7-windows-amd64" { } ''
  mkdir -p $out/bin $out/chipdb $out/libexec
  mkdir -p $out/share/nextpnr/external/prjxray-db $out/lib/python3.12/site-packages

  # -- native Windows executables
  cp -L ${nextpnrWin}/bin/*.exe $out/bin/
  cp -L ${prjxrayWin}/bin/*.exe $out/bin/

  # -- runtime DLLs next to the exes (Windows searches the app dir first).
  # libpython + winpthread/mcfgthread/gcc_s sit in the mingw python's bin/;
  # libstdc++ comes from the gcc lib output.
  cp -L ${mingwPython}/bin/libpython3.11.dll ${mingwPython}/bin/libwinpthread-1.dll \
        ${mingwPython}/bin/libmcfgthread-1.dll ${mingwPython}/bin/libgcc_s_seh-1.dll $out/bin/
  cp -L ${gccLib}/libstdc++-6.dll $out/bin/

  # -- nextpnr's embedded-python stdlib at lib/python3.11 (parent of bin/). The
  # interpreter finds it via getpath relative to the exe -> no PYTHONHOME, so it
  # never clashes with the oss-cad-suite python that runs fasm2frames.
  mkdir -p $out/lib/python3.11
  cp -r ${mingwPython}/lib/python3.11/. $out/lib/python3.11/
  chmod -R u+w $out/lib/python3.11
  # the report script only needs json/os/pathlib + interpreter startup; drop the
  # big unused parts to keep the package smaller.
  rm -rf $out/lib/python3.11/test $out/lib/python3.11/idlelib \
         $out/lib/python3.11/tkinter $out/lib/python3.11/turtledemo \
         $out/lib/python3.11/lib2to3 $out/lib/python3.11/ensurepip
  find $out/lib/python3.11 -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

  # -- chipdb (the parts from chipdb-parts.json, like openxc7-pack.py) + data
  ${lib.concatMapStringsSep "\n  " (p: "cp ${chipdb}/${p}.bin $out/chipdb/") chipdbParts}
  cp -r ${nextpnr-xilinx}/share/nextpnr/external/prjxray-db/artix7 \
        $out/share/nextpnr/external/prjxray-db/
  cp -r ${nextpnr-xilinx}/share/nextpnr/python/. $out/share/nextpnr/python/ 2>/dev/null || \
    mkdir -p $out/share/nextpnr/python

  # -- pure-python tools (strip native extensions -> Windows uses textX fallback)
  # dirs/files copied from the store come read-only -> chmod like the
  # python3.11 stdlib above, or the find -delete and the util.py replace fail
  cp -r ${pyEnv}/lib/python3.12/site-packages/. $out/lib/python3.12/site-packages/
  chmod -R u+w $out/lib/python3.12/site-packages
  find $out/lib/python3.12/site-packages \
       \( -name '*.so' -o -name '*.dylib' -o -name '*.pyd' -o -name 'libparse_fasm*' \) -delete
  # prjxray python module + the python tool scripts
  cp -r ${prjxray}/usr/share/python3/prjxray $out/lib/python3.12/site-packages/
  chmod -R u+w $out/lib/python3.12/site-packages/prjxray
  cp ${prjxray}/bin/fasm2frames ${prjxray}/bin/bit2fasm $out/libexec/
  chmod u+w $out/libexec/fasm2frames $out/libexec/bit2fasm
  # -- POSIX-ism fixes (systematic audit 2026-07-12): these scripts run under
  # -- oss-cad-suite's WINDOWS python in apio. Guards fail the build if the
  # -- upstream text drifts. Upstream PR material (f4pga/prjxray).
  # fasm2frames: the '/dev/stdout' default does not exist on Windows; apio
  # invokes it with a shell redirect, so default to sys.stdout instead
  sed -i "s|^import argparse$|import argparse\nimport sys|" $out/libexec/fasm2frames
  sed -i "s|default='/dev/stdout',|default=None,|" $out/libexec/fasm2frames
  sed -i "s|f_out=open(args.fn_out, 'w'),|f_out=(open(args.fn_out, 'w') if args.fn_out else sys.stdout),|" $out/libexec/fasm2frames
  grep -q "args.fn_out else sys.stdout" $out/libexec/fasm2frames || { echo "fasm2frames patch failed"; exit 1; }
  # bit2fasm: a NamedTemporaryFile kept open cannot be written by the
  # bitread.exe subprocess on Windows (sharing violation) -> close it first
  sed -i "s|bits_file = stack.enter_context(tempfile.NamedTemporaryFile())|bits_file = stack.enter_context(tempfile.NamedTemporaryFile(delete=False)); bits_file.close(); stack.callback(os.unlink, bits_file.name)|" $out/libexec/bit2fasm
  grep -q "delete=False" $out/libexec/bit2fasm || { echo "bit2fasm patch failed"; exit 1; }
  ${lib.optionalString (utilPatch != null)
    "install -m 644 ${utilPatch} $out/lib/python3.12/site-packages/prjxray/util.py"}

  # -- Windows launchers (apio/oss-cad-suite provides the Windows python)
  ${cmdLauncher "fasm2frames"}
  ${cmdLauncher "bit2fasm"}

  echo "windows-amd64" > $out/VERSION.platform
  chmod -R u+w $out
''
