# Reproducible assembly of the apio-openxc7-windows-amd64 package, cross-built
# from x86_64-linux with pkgsCross.mingwW64. Build with:
#   nix build .#packages.x86_64-linux.openxc7-windows-amd64
#
# The result ($out) is the package TREE; the dated .tgz is produced by CI
# (.github/workflows/windows-package.yml) so the date stays out of the pure
# nix build.
#
# Reuses the flake's native derivations for the platform-independent parts
# (chipdb .bin, prjxray-db data, nextpnr python, fasm/prjxray python). Only the
# native .exe come from the mingw cross build here.
{ pkgs
, lib
, nextpnr-xilinx           # native: provides share/ data + python
, prjxray                  # native: provides prjxray python + fasm2frames/bit2fasm
, fasm                     # native python package (pulls textx -> arpeggio)
, nextpnr-xilinx-chipdb    # native: artix7 chipdb has xc7a35tcpg236.bin
, utilPatch ? null         # store/util.py (prjxray flock workaround), optional
}:

let
  # mingw cross package set, re-imported with allowUnsupportedSystem so the
  # conservative meta.platforms of header-only deps (eigen) don't block the
  # cross eval (they cross-compile fine). Equivalent to pkgs.pkgsCross.mingwW64.
  cross = import pkgs.path {
    localSystem = pkgs.system;
    crossSystem = pkgs.lib.systems.examples.mingwW64;
    config.allowUnsupportedSystem = true;
  };
  python = pkgs.python3;

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
    "-DARCH=xilinx" "-DBUILD_GUI=OFF" "-DBUILD_TESTS=OFF" "-DBUILD_PYTHON=OFF"
    "-DUSE_OPENMP=OFF" "-Wno-deprecated" "-DCURRENT_GIT_VERSION=3374e5a"
    "-DPython3_EXECUTABLE=${python.interpreter}"
  ];

  # boost without zstd: zstd(mingw) -> gnugrep(mingw) -> bash(mingw) doesn't cross
  boostNoZstd = cross.boost.overrideAttrs (o: {
    buildInputs = builtins.filter
      (p: !(lib.hasInfix "zstd" (p.name or ""))) (o.buildInputs or []);
  });

  # nextpnr two-stage cross: native bbasm -> ImportExecutables.cmake -> cross import
  bba = pkgs.stdenv.mkDerivation {
    pname = "nextpnr-xilinx-bbasm-native"; version = "0.8.2";
    src = nextpnrSrc;
    nativeBuildInputs = [ pkgs.cmake pkgs.git python ];
    buildInputs = [ pkgs.boost pkgs.eigen ];
    cmakeFlags = commonFlags;
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
    nativeBuildInputs = [ pkgs.cmake pkgs.git python ];
    buildInputs = [ boostNoZstd cross.eigen cross.windows.mingw_w64_pthreads ];
    enableParallelBuilding = true;
    # router2: boost::container::flat_map's sorted invariant breaks on mingw
    # (count() true but at() throws) -> std::map. No change on Linux. Upstream PR.
    postPatch = ''
      sed -i 's|boost::container::flat_map<int, std::pair<int, PipId>> bound_nets;|std::map<int, std::pair<int, PipId>> bound_nets;|' common/router2.cc
      grep -q '#include <map>' common/router2.cc || \
        sed -i 's|#include <boost/container/flat_map.hpp>|#include <boost/container/flat_map.hpp>\n#include <map>|' common/router2.cc
    '';
    cmakeFlags = commonFlags ++ [ "-DIMPORT_EXECUTABLES=${bba}/ImportExecutables.cmake" ];
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
    buildInputs = [ boostNoZstd cross.eigen cross.windows.mingw_w64_pthreads ];
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

  chipdb = nextpnr-xilinx-chipdb.artix7;   # contains xc7a35tcpg236.bin

  # pure-python tool env (fasm pulls textx -> arpeggio; + prjxray's python deps).
  # withPackages keeps the *.dist-info metadata (textX needs version("textx")).
  pyEnv = python.withPackages (ps: [
    fasm ps.simplejson ps.intervaltree ps.sortedcontainers ps.pyyaml
  ]);

  cmdLauncher = name: ''
    printf '@echo off\r\nset "PKG=%%~dp0.."\r\nset "PYTHONPATH=%%PKG%%\\lib\\python3.12\\site-packages;%%PYTHONPATH%%"\r\npython "%%PKG%%\\libexec\\${name}" %%*\r\n' > $out/bin/${name}.cmd
  '';

in pkgs.runCommand "apio-openxc7-windows-amd64" { } ''
  mkdir -p $out/bin $out/chipdb $out/libexec
  mkdir -p $out/share/nextpnr/external/prjxray-db $out/lib/python3.12/site-packages

  # -- native Windows executables + runtime DLLs (next to the exes)
  cp -L ${nextpnrWin}/bin/*.exe $out/bin/
  cp -L ${prjxrayWin}/bin/*.exe $out/bin/
  for d in ${nextpnrWin}/bin/*.dll ${prjxrayWin}/bin/*.dll; do
    [ -e "$d" ] && cp -Lf "$d" $out/bin/ || true
  done

  # -- chipdb (single part, like openxc7-pack.py) + data
  cp ${chipdb}/xc7a35tcpg236.bin $out/chipdb/
  cp -r ${nextpnr-xilinx}/share/nextpnr/external/prjxray-db/artix7 \
        $out/share/nextpnr/external/prjxray-db/
  cp -r ${nextpnr-xilinx}/share/nextpnr/python/. $out/share/nextpnr/python/ 2>/dev/null || \
    mkdir -p $out/share/nextpnr/python

  # -- pure-python tools (strip native extensions -> Windows uses textX fallback)
  cp -r ${pyEnv}/lib/python3.12/site-packages/. $out/lib/python3.12/site-packages/
  find $out/lib/python3.12/site-packages \
       \( -name '*.so' -o -name '*.dylib' -o -name '*.pyd' -o -name 'libparse_fasm*' \) -delete
  # prjxray python module + the python tool scripts
  cp -r ${prjxray}/usr/share/python3/prjxray $out/lib/python3.12/site-packages/
  cp ${prjxray}/bin/fasm2frames ${prjxray}/bin/bit2fasm $out/libexec/
  ${lib.optionalString (utilPatch != null)
    "cp ${utilPatch} $out/lib/python3.12/site-packages/prjxray/util.py"}

  # -- Windows launchers (apio/oss-cad-suite provides the Windows python)
  ${cmdLauncher "fasm2frames"}
  ${cmdLauncher "bit2fasm"}

  echo "windows-amd64" > $out/VERSION.platform
  chmod -R u+w $out
''
