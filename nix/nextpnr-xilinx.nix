{ stdenv, cmake, git, lib, fetchFromGitHub, python312Packages, python312
, eigen, pkg-config, prjxray-db, ... }:
let
  # Kept in a let so the version stamp below can read .rev. If local
  # patches ever return, wrap this in applyPatches AT THE SOURCE so the
  # binary, the chipdb generator and the Windows cross see one tree.
  upstream = fetchFromGitHub {
    owner = "openXC7";
    repo = "nextpnr";
    rev = "c8a7946f9f312d2672ae6af4e2b4dbbc41ea5ff9";
    hash = "sha256-6dWIBUdBJH9YRUjkv+Argj4RSpkQV770Js9L7m3/lSU=";
    # himbaechel/uarch/xilinx/meta (openXC7/nextpnr-xilinx-meta a4af910c)
    # is what the chipdb generator reads the site and wire metadata from.
    fetchSubmodules = true;
  };
in
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "0-unstable-2026-09-22";

  # The himbaechel xilinx uarch of openXC7/nextpnr (apio#1070): the engine
  # the package moves to from the nextpnr-xilinx fork. The repository has
  # no tags, so the revision above is the version, as it always was here.
  # main of 2026-09-22; everything since the tree measured against
  # nextpnr-xilinx 0.9.5 (0ebc9a1f) is CI only. ZERO local patches.
  #
  # It installs as bin/nextpnr-xilinx, the name apio runs (the engine is
  # named in XILINX-PARTS-INDEX.json, not by the executable), and it
  # takes another command line than the fork: the part in --device, the
  # XDC and the FASM as uarch options (-o xdc=, -o fasm=), one chipdb per
  # die in --chipdb, and the metrics in --report.
  #
  # The chipdb files are not built here: pack/chipdb.py generates one per
  # die of the manifest with the generator of this very source tree
  # (passthru.chipdbGenerator) and this build's bbasm, and the release
  # publishes them. So the build is told about no device at all.
  src = upstream;

  nativeBuildInputs = [ cmake git pkg-config ];
  buildInputs = [ python312Packages.boost python312 eigen ];

  # Apple clang rejects a std::string passed to log_error (a variadic
  # function) as a hard error. GCC, which builds this tree on Linux and
  # for the mingw cross, accepts it. The call is the LUT-RAM clock
  # inversion disagreement diagnostic in the xilinx fasm writer; it is
  # not on the path that emits a bitstream. The flag lets clang compile
  # the same sources. It is not a change to those sources.
  preConfigure = lib.optionalString stdenv.isDarwin ''
    export NIX_CFLAGS_COMPILE="$NIX_CFLAGS_COMPILE -Wno-non-pod-varargs"
  '';

  cmakeFlags = [
    # 8 hex digits: what `git describe --always` prints for this tree, so
    # --version reads the same as a build from a checkout.
    "-DCURRENT_GIT_VERSION=${lib.substring 0 8 upstream.rev}"
    "-DARCH=himbaechel"
    "-DHIMBAECHEL_UARCH=xilinx"
    # Required by the uarch's CMakeLists even with no device to build.
    "-DHIMBAECHEL_PRJXRAY_DB=${prjxray-db}"
    "-DHIMBAECHEL_XILINX_DEVICES="
    "-DBUILD_GUI=OFF"
    "-DBUILD_TESTS=OFF"
    # The embedded interpreter is unused: metrics come from --report.
    # OFF drops libpython from the binary (and, on Windows, a cross-built
    # CPython from the tools tree). Canonical FASM of the manifest blinkys
    # and of the regression suite is byte-identical to the same sources
    # built with it ON, so the IdString order does not move.
    "-DBUILD_PYTHON=OFF"
    # USE_OPENMP stays at its default, OFF: that is the build the engine
    # was measured with against nextpnr-xilinx 0.9.5, and turning it on
    # is a factor of its own to measure before it ships.
    "-Wno-deprecated"
    # Point FindPython3 at the nix interpreter EXPLICITLY. Without these,
    # cmake's search can wander into the host (macOS SDK/CLT): the same
    # derivation built on a dev Mac (where an impure Python.h happened to
    # be findable) and died on the clean macos-14 runner with
    # "fatal error: 'Python.h' file not found" (first public CI run,
    # 2026-08-06). Purity means not depending on that luck anywhere.
    "-DPython3_EXECUTABLE=${python312}/bin/python3.12"
    "-DPython3_INCLUDE_DIR=${python312}/include/python3.12"
    "-DPython3_LIBRARY=${python312}/lib/libpython3.12${stdenv.hostPlatform.extensions.sharedLibrary}"
  ];

  # The release flags carry -g: ~88 of the 95 MB of nextpnr-himbaechel are
  # .debug_* sections. The fixup phase strips bin/ (nix's default), which
  # is what leaves a binary of a few MB.
  installPhase = ''
    runHook preInstall
    install -Dm755 nextpnr-himbaechel $out/bin/nextpnr-xilinx
    install -Dm755 bba/bbasm $out/bin/bbasm
    mkdir -p $out/share/nextpnr/external
    ln -s ${prjxray-db} $out/share/nextpnr/external/prjxray-db
    runHook postInstall
  '';

  passthru = {
    inherit prjxray-db;
    # Run with a python 3: --xray <db>/<family> --device <die> --bba <out>.
    # It reads the uarch's constids.inc and meta/ next to itself, so it is
    # used in place, from the source tree the binary was built from.
    chipdbGenerator = "${upstream}/himbaechel/uarch/xilinx/gen/xilinx_gen.py";
  };

  meta = with lib; {
    description = "Place and route for Xilinx 7-series FPGAs (the himbaechel xilinx uarch of nextpnr)";
    homepage = "https://github.com/openXC7/nextpnr";
    license = licenses.isc;
    platforms = platforms.all;
  };
}
