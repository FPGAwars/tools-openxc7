{ stdenv, cmake, git, lib, fetchFromGitHub, applyPatches, python312Packages
, python312, eigen, pkg-config, llvmPackages, ... }:
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "unstable-2026-08-03";

  # stable-backports tip (PRs #102 and #104 took all eight of our previous
  # local patches upstream), plus ONE local patch pending its own PR:
  # xc7-slice-validation-strength fixes a second defect of 6b46121f, found
  # 2026-08-03 by our regression suite — the frozen-tile fast-path and the
  # pin-merge skip both keyed on STRENGTH_STRONG, which is how HeAP binds the
  # chains it places, so carry chains / mux trees skipped slice validation
  # AND input-pin merging (two nets on one physical A-pin -> router failure),
  # and the O6-name check contradicted fixupPlacement's rename contract
  # (which made strict validation hang instead).
  #
  # The patch is applied to the SOURCE (applyPatches) so every consumer —
  # the native build, the chipdb derivation and the Windows cross build —
  # sees the same tree from one single place, instead of the hand-synced
  # per-derivation patch lists that shipped a half-updated package once.
  src = applyPatches {
    name = "nextpnr-xilinx-source";
    src = fetchFromGitHub {
      owner = "openXC7";
      repo = "nextpnr-xilinx";
      rev = "a9badf1d36ad4bf1087898c91abc09dde952cc83";
      hash = "sha256-zHhD4dpMADaILtWZC2PVNWDPrad8Ms8JmpcGNtK4gCU=";
      fetchSubmodules = true;
    };
    patches = [ ./patches/xc7-slice-validation-strength.patch ];
  };

  # 0.9.x detects eigen via pkg-config (upstream 77911357)
  nativeBuildInputs = [ cmake git pkg-config ];
  buildInputs = [ python312Packages.boost python312 eigen ]
    ++ (lib.optionals stdenv.cc.isClang [ llvmPackages.openmp ]);

  cmakeFlags = [
    "-DCURRENT_GIT_VERSION=${lib.substring 0 7 src.rev}"
    "-DARCH=xilinx"
    "-DBUILD_GUI=OFF"
    "-DBUILD_TESTS=OFF"
    "-DUSE_OPENMP=ON"
    "-Wno-deprecated"
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
