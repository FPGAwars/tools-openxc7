# GATE X-B spike: cross-compile nextpnr-xilinx to native Windows (mingw-w64)
# WITHOUT python embedding. Local sources (server can't reach github.com).
#
# Two-stage, the standard nextpnr cross recipe:
#  1) native build of the `bbasm` tool -> exports ImportExecutables.cmake
#  2) cross build importing it (-DIMPORT_EXECUTABLES=...), since a Windows
#     bbasm can't run on the Linux build host.
# Plus: boost without zstd (zstd->gnugrep->bash(mingw) doesn't cross), and a
# native python3 interpreter for nextpnr's unconditional find_package(Python3).
let
  pkgs  = import ./nixpkgs-src {};
  lib   = pkgs.lib;
  cross = pkgs.pkgsCross.mingwW64;
  src   = ./nextpnr-src;

  commonFlags = [
    "-DARCH=xilinx"
    "-DBUILD_GUI=OFF"
    "-DBUILD_TESTS=OFF"
    "-DBUILD_PYTHON=OFF"
    "-DUSE_OPENMP=OFF"
    "-Wno-deprecated"
    "-DCURRENT_GIT_VERSION=3374e5a"
    "-DPython3_EXECUTABLE=${pkgs.python3.interpreter}"
  ];

  boostNoZstd = cross.boost.overrideAttrs (old: {
    buildInputs = builtins.filter
      (p: !(lib.hasInfix "zstd" (p.name or "")))
      (old.buildInputs or []);
  });

  # 1) NATIVE bbasm + exported import file (rewritten to the installed path)
  nativeBba = pkgs.stdenv.mkDerivation {
    pname = "nextpnr-xilinx-bbasm-native";
    version = "0.8.2";
    inherit src;
    nativeBuildInputs = [ pkgs.cmake pkgs.git pkgs.python3 ];
    buildInputs = [ pkgs.boost pkgs.eigen ];
    cmakeFlags = commonFlags;
    buildFlags = [ "bbasm" ];
    installPhase = ''
      mkdir -p $out/bin
      cp bbasm $out/bin/
      sed "s|IMPORTED_LOCATION \"[^\"]*\"|IMPORTED_LOCATION \"$out/bin/bbasm\"|" \
        ImportExecutables.cmake > $out/ImportExecutables.cmake
      echo "=== ImportExecutables.cmake ==="; cat $out/ImportExecutables.cmake
    '';
  };

in cross.stdenv.mkDerivation {
  pname = "nextpnr-xilinx-win";
  version = "0.8.2";
  inherit src;
  nativeBuildInputs = [ pkgs.cmake pkgs.git pkgs.python3 ];
  # nextpnr's CMakeLists unconditionally does target_link_libraries(... pthread);
  # mingw_w64_pthreads provides libpthread.a so -lpthread resolves on Windows.
  buildInputs = [ boostNoZstd cross.eigen cross.windows.mingw_w64_pthreads ];
  enableParallelBuilding = true;
  # router2: boost::container::flat_map's sorted invariant breaks on this mingw
  # build (count() returns true but at() throws) -> crash. std::map fixes it;
  # verified identical canonical fasm on Linux. Upstream PR material.
  postPatch = ''
    sed -i 's|boost::container::flat_map<int, std::pair<int, PipId>> bound_nets;|std::map<int, std::pair<int, PipId>> bound_nets;|' common/router2.cc
    grep -q '#include <map>' common/router2.cc || \
      sed -i 's|#include <boost/container/flat_map.hpp>|#include <boost/container/flat_map.hpp>\n#include <map>|' common/router2.cc
  '';
  cmakeFlags = commonFlags ++ [
    "-DIMPORT_EXECUTABLES=${nativeBba}/ImportExecutables.cmake"
  ];
  installPhase = ''
    mkdir -p $out/bin
    echo "=== exes in build dir ==="; ls -la *.exe || true
    cp -v *.exe $out/bin/ || true
    test -f $out/bin/nextpnr-xilinx.exe
  '';
  dontStrip = true;
}
