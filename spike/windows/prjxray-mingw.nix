# GATE X (prjxray): cross-compile prjxray's C++ tools to native Windows
# (mingw-w64). Local sources. Same workarounds as nextpnr: boost w/o zstd,
# native python3, mingw pthreads, allow-unsupported (eigen). prjxray bundles
# gflags/abseil/cctz/yaml-cpp as submodules and runs no built tool at build
# time, so there is no cross chicken-egg.
let
  pkgs  = import ./nixpkgs-src {};
  lib   = pkgs.lib;
  cross = pkgs.pkgsCross.mingwW64;

  boostNoZstd = cross.boost.overrideAttrs (old: {
    buildInputs = builtins.filter
      (p: !(lib.hasInfix "zstd" (p.name or "")))
      (old.buildInputs or []);
  });
in cross.stdenv.mkDerivation {
  pname = "prjxray-win";
  version = "bdbc665";
  src = ./prjxray-src;
  nativeBuildInputs = [ pkgs.cmake pkgs.git pkgs.python3 ];
  buildInputs = [ boostNoZstd cross.eigen cross.windows.mingw_w64_pthreads ];
  enableParallelBuilding = true;

  postPatch = ''
    # Windows ports of the two POSIX-only files (mmap + glob). #ifdef _WIN32,
    # Linux path unchanged -> upstreamable to f4pga/prjxray.
    cp ${./patches/memory_mapped_file.cc} lib/memory_mapped_file.cc
    cp ${./patches/database.cc} lib/database.cc
    sed -i '29 itarget_compile_options(libprjxray PUBLIC "-Wno-deprecated")' lib/CMakeLists.txt || true
  '';

  cmakeFlags = [
    "-DCMAKE_BUILD_TYPE=Release"
    "-Wno-deprecated"
    "-DPython3_EXECUTABLE=${pkgs.python3.interpreter}"
    # mingw treats explicit template instantiations (Configuration<Spartan6>)
    # as strong symbols and reports a duplicate vs the implicit one in the
    # tools; both are identical so taking either is safe. (Upstream fix would
    # be inline/extern-template; this is the spike workaround.)
    "-DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-multiple-definition"
  ];

  installPhase = ''
    mkdir -p $out/bin
    echo "=== exes produced ==="; find . -name '*.exe' | head -40
    for t in xc7frames2bit bitread xc7patch bittool segmatch; do
      f=$(find . -name "$t.exe" | head -1)
      [ -n "$f" ] && cp -v "$f" $out/bin/ || echo "  (missing $t.exe)"
    done
    ls -la $out/bin
    test -f $out/bin/xc7frames2bit.exe
  '';
  dontStrip = true;
}
