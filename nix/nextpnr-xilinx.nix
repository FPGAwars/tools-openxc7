{ stdenv, cmake, git, lib, fetchFromGitHub, applyPatches, python312Packages
, python312, eigen, pkg-config, llvmPackages, ... }:
let
  # Kept in a let so the version stamp below can read .rev (a lesson from
  # the applyPatches era: it returns a plain store path without attributes).
  # If local patches ever return, wrap this in applyPatches AT THE SOURCE so
  # native, chipdb and the Windows cross see one tree.
  upstream = fetchFromGitHub {
    owner = "openXC7";
    repo = "nextpnr-xilinx";
    rev = "ece39e171b03180c0efd6ba024ef175ce3ad0aad";
    hash = "sha256-6xzb3N86mRlh81uSNRR1q1hoYPceW4nvCP6wbY062ag=";
    fetchSubmodules = true;
  };
in
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "0.9.4";

  # Upstream release 0.9.4 (2026-09-09), 45 commits over 0.9.3. The
  # regional-clocking series lands complete: create_clock propagated through
  # buffers and PLL/MMCM (#156), BUFIO packed onto its own bel (#157), a
  # pad-fed BUFIO and BUFR each constrained to the site their pad reaches
  # (#168, #170), a regional buffer's sinks kept inside its clock region
  # (#171) and BUFIO_Yn.IN_USE emitted for a placed BUFIO (#167) -- 0.9.3
  # could not place a BUFIO at all. With it: CARRY4 O fanout relocated at
  # the chain root (#164), the X_ORIG_PORT naming fixes, and AssassinK786's
  # round of encoding fixes -- FDSE/FDPE undefined INIT (#179), SRL16E and
  # SRLC32E INIT actually reaching the bitstream (#185), WEMUX consistency
  # across a SLICEM half-tile (#186), constant-tied STARTUPE2 control pins
  # disconnected instead of routed (#190), MMCM/PLL IS_PWRDWN_INVERTED and
  # the MMCM PHASE default (#191); #183 is reverted upstream. ZERO local
  # patches.
  #
  # Two database bumps ride along (77e52f10 -> 6b8695e -> e8b8e8e4): the
  # artix7 BUFRCLK enables and MMCM performance-clock rows, the zynq7 and
  # spartan7 CLK_HROW BUFG-cascade rows -- which is what lets the two
  # xc7z045 900-ball footprints back into the manifest -- and the spartan7
  # part databases for xc7s6/xc7s15/xc7s25/xc7s75/xc7s100, which take the
  # packaged database from 154 parts to 202.
  #
  # constids.inc and bbaexport are untouched, and so are every tile_type
  # json and every packaged fabric's tilegrid/tileconn: the database grew
  # segbits (read by fasm2frames, not by the exporter) and parts of families
  # we do not build. The chipdb bins therefore keep their content and only
  # the identity stamp moves -- CI regenerates them, old seeds are rejected,
  # as designed.
  src = upstream;

  # 0.9.x detects eigen via pkg-config (upstream 77911357)
  nativeBuildInputs = [ cmake git pkg-config ];
  buildInputs = [ python312Packages.boost python312 eigen ]
    ++ (lib.optionals stdenv.cc.isClang [ llvmPackages.openmp ]);

  cmakeFlags = [
    "-DCURRENT_GIT_VERSION=${lib.substring 0 7 upstream.rev}"
    "-DARCH=xilinx"
    "-DBUILD_GUI=OFF"
    "-DBUILD_TESTS=OFF"
    "-DUSE_OPENMP=ON"
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

  installPhase = ''
    mkdir -p $out/bin
    cp nextpnr-xilinx bbasm $out/bin/
    mkdir -p $out/share/nextpnr/external
    cp -rv ../xilinx/external/prjxray-db $out/share/nextpnr/external/
    cp -rv ../xilinx/external/nextpnr-xilinx-meta $out/share/nextpnr/external/
    cp -rv ../xilinx/python/ $out/share/nextpnr/python/
    cp ../xilinx/constids.inc $out/share/nextpnr
  '';

  meta = with lib; {
    description = "Place and route tool for FPGAs";
    homepage = "https://github.com/openXC7/nextpnr-xilinx";
    license = licenses.isc;
    platforms = platforms.all;
  };
}
