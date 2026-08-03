{ stdenv, cmake, git, lib, fetchFromGitHub, python312Packages, python312, eigen
, pkg-config, llvmPackages, ... }:
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "unstable-2026-08-03";

  # stable-backports tip. Every fix we used to carry as a local patch is now
  # upstream: PR #102 (2026-08-01) took the global const node, the XDC virtual
  # clock, the per-clock fmax getter, both timing-walk fixes, the DSP48E1
  # timing model and the two mingw ones; PR #104 (2026-08-03) took the router2
  # reservation fix, which is what kept this pinned to a pre-0.9.x commit —
  # 6b46121f made any registered counter unroutable and its fix had never been
  # pushed. Hence: no patches at all, for the first time.
  src = fetchFromGitHub {
    owner = "openXC7";
    repo = "nextpnr-xilinx";
    rev = "a9badf1d36ad4bf1087898c91abc09dde952cc83";
    hash = "sha256-zHhD4dpMADaILtWZC2PVNWDPrad8Ms8JmpcGNtK4gCU=";
    fetchSubmodules = true;
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
