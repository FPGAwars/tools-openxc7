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
    rev = "a70ae4a8dea19423ec50b4f7e255c1b6724644ba";
    hash = "sha256-gQ5k/DyEQudDvW5IHsNnJytxaLcMrb4qjoEdO9UE2iI=";
    fetchSubmodules = true;
  };
in
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "unstable-2026-08-03";

  # stable-backports tip (2026-08-05): our PRs #105 (slice validation
  # strength marker) and #106 (SRL cascade packing + DI1MUX fasm names)
  # merged upstream — ZERO local patches for the first time. PRs #102/#104
  # took the previous eight.
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
    # Pin FindPython3 to the nix interpreter EXPLICITLY. Without these,
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
