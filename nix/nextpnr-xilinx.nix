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
    rev = "a9ceeec26770f6d1ea97c6afd8cf731a587afcf1";
    hash = "sha256-f9t1HdpmV/Wucga19RJXdagik3qbcF0IMTVsm7qWmVw=";
    fetchSubmodules = true;
  };
in
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "0.9.5";

  # Upstream release 0.9.5 (2026-09-13), 17 commits over 0.9.4, in three
  # blocks.
  #
  # shenki's constant-net series (#184): routeVcc() hands back the constant
  # sinks it could not reach, routeConstants() places a constant INIT LUT
  # next to each of them, moves that sink wire's whole group of users onto
  # it and re-routes, and anything still unreached is an ERROR unless
  # --allow-const-holdouts is given. An unprogrammed IMUX reads 1 on xc7, so
  # a RAM32M address bit tied to ground used to float high while nextpnr
  # exited 0. Two router2 fixes come with it -- release a net's old binding
  # before rebinding, and adopt pre-existing routing with the arc state the
  # ripup path expects -- both needed because that series re-routes an
  # already routed design. The new flag is a plain bool on Arch, not a
  # ctx->settings entry, so it interns no IdString before packing (the
  # ordering effect measured in nextpnr-xilinx#184).
  #
  # AssassinK786's #187 closes the BUFHCE pass-through: the CE pin of a
  # BUFHCE used as a pure route-thru was left floating with ZINV_CE set
  # unconditionally. It is now bridged explicitly to $PACKER_VCC_NET, which
  # is what the database already defaults that IMUX to, so every pip the
  # bridge binds is bitless and the emitted bitstream is unchanged -- the
  # variant measured against the five Vivado golden references of #177.
  #
  # And the database gitlink follows prjxray-db to 1768fb35 (db#15): the
  # REAL xc7s25 device model, in place of the copy of the xc7s50 fabric that
  # addressed the wrong frames (clock configuration column 19 against the
  # model's 23, a 3060-frame image against 4970), plus the MONITOR_*_FUJI2
  # tile types it needs; complete part.json for the xc7s6/xc7s15/xc7s50-1Q/
  # xc7s75/xc7s100 packages; and xc7s75 off its own bogus fabric copy. That
  # model is the precondition xc7s25csga324 was waiting on to enter the
  # manifest.
  #
  # constids.inc and bbaexport are untouched and no family other than
  # spartan7 changes in the database, so the chipdb bins of the parts we
  # already built keep their content: only the identity stamp moves, CI
  # regenerates them and rejects older seeds, as designed. ZERO local
  # patches.
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
