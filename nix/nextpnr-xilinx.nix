{ stdenv, cmake, git, lib, fetchFromGitHub, python312Packages, python312, eigen
, pkg-config, llvmPackages, ... }:
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "unstable-2026-07-13";

  # Last commit BEFORE the 0.9.x routing regression (same-slice FF->LUT
  # feedback arc unroutable since 6b46121f; bisected 2026-07-30). Re-pin to
  # the 0.9.x tag once upstream fixes it — everything else here already
  # builds 0.9.1.
  src = fetchFromGitHub {
    owner = "openXC7";
    repo = "nextpnr-xilinx";
    rev = "27727428c13f60849fef9f85a814793db06390bb";
    hash = "sha256-zzBk04/KDwCR3CjHmejAJG/fL5I3YpEj8SZKajVZ+64=";
    fetchSubmodules = true;
  };

  # The global const node in the chipdb only included the GLBL wires of
  # column x=0, but pseudo const driver bels exist in every tile: a driver
  # placed elsewhere could only feed its own row -> router error "Invalid
  # global constant node" on VCC/GND-to-pad and PLL designs (openXC7 #38/#41,
  # gatecat#54). Root-caused 2026-07-12; upstream PR material.
  patches = [
    ./patches/bbaexport-global-const-node.patch
    # XDC parser: a "virtual clock" (create_clock without target ports/nets,
    # common in Vivado XDCs for I/O timing) crashed with an uncaught
    # std::out_of_range; ignore it with a warning instead. Upstream PR material.
    ./patches/xdc-virtual-clock-crash.patch
    # The fork lacks mainline's --report; expose per-clock fmax/target to the
    # embedded Python (ctx.reportClockFmaxJson(), computed on demand on the
    # routed design) so --post-route scripts (apio report) can emit the clock
    # table. Upstream PR material.
    ./patches/timing-fmax-python.patch
    # (frontend-hier-merge-nets.patch retired 2026-07-30: 0.9.x already
    # carries the fix as upstream commit c7c655d5.)
    # The xc7 post-route LUT pin fixup can bind a cell input pin to the
    # cell's own output net (router feeding the output back through an
    # unused input pin of the site); the timing walk then saw a false
    # combinational loop and aborted post-route analysis for the WHOLE
    # design ("timing analysis failed due to presence of combinatorial
    # loops...", empty apio report table). Filter self-net arcs on both
    # sides of the fanin bookkeeping. Found with an Icestudio VGA design
    # with F7 muxes (wide-LUT clusters). Upstream PR material.
    ./patches/timing-selfloop-arcs.patch
    ./patches/timing-lut-shared-pins.patch
    ./patches/timing-dsp48-comb.patch
  ];

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
