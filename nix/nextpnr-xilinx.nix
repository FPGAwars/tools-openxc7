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
    rev = "0eae9fbb19dfb83cdd30d5048d8b0ba744180ad0";
    hash = "sha256-2zE4sOLAvdw+sf7ZoNwDEIlqs5osrSn1Z0q/Que5cV8=";
    fetchSubmodules = true;
  };
in
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "0.9.7";

  # Upstream release 0.9.7 (2026-09-23), 19 commits over 0.9.5 (0.9.6 is
  # the intermediate tag). Grouped by what they change in a build.
  #
  # IOB defaults now match Vivado (gHashTag's #120): the default LVCMOS33/
  # LVTTL drive (12) emits DRIVE.I12_I16 instead of I12_I8, and HR-bank
  # input-only pads no longer get SLEW.SLOW. Both were found against the
  # Vivado-built references prjxray-db ships under artix7/harness; they move
  # two bits on almost every output pad and one on every HR input pad, so
  # the bitstream of nearly every design changes, by design.
  #
  # The database gitlink follows prjxray-db to a90f27c1 (db#18/#20/#21):
  # the top-SING IOB33/IOI3 tiles of xc7s25, xc7s100 and xc7vx485t carry
  # alias start_offset 0, so fasm2frames writes pads such as J6/L13/G13 of
  # the xc7s25 into their own tile instead of the neighbouring one (a design
  # using J6 together with L4/K4 used to fail with FasmInconsistentBits);
  # plus the real xc7s100/xc7s75 tilegrid (db#17). artix7, zynq7 and the
  # other spartan7 devices are untouched.
  #
  # Packer, placer and backend fixes: RAMB36E1 data-cascade pairs are moved
  # onto the one bel the cascade can reach after placement (#204, a no-op
  # without cascades); a LUT-RAM with an inverted write clock drives the
  # half-slice CLKINV (#203); RAM64X1S packs (#196); constant-driven
  # STARTUPE2 pins are routed again, as Vivado does (#194); a warning names
  # two IOs constrained to the same package pin (#197); the verbose timing
  # walk no longer asserts on unrouted nets (#200).
  #
  # constids.inc and bbaexport are untouched and the only db tilegrid in
  # our manifest that changes is xc7s25's, whose chipdb does not encode
  # start_offset. ZERO local patches.
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
