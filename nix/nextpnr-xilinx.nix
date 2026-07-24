{ stdenv, cmake, git, lib, fetchFromGitHub, python312Packages, python312, eigen
, llvmPackages, ... }:
stdenv.mkDerivation rec {
  pname = "nextpnr-xilinx";
  version = "0.8.2";

  src = fetchFromGitHub {
    owner = "openXC7";
    repo = "nextpnr-xilinx";
    rev = "3374e5a62b54dc346fd5f85188ed24075ddfd5fb";
    hash = "sha256-gW3Z3Cd5/gfX7k/ekRHtPVlbhKszWah1L+HggMFKakA=";
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
    # Backport from mainline nextpnr: the JSON frontend never grew
    # net_old_indices, so the FIRST merge_nets() during hierarchical import
    # (any non-flattened multi-module design where a submodule net maps to
    # two parent nets) died with std::out_of_range. Found with an Icestudio
    # VGA design (yosys synth_xilinx does not flatten by default).
    ./patches/frontend-hier-merge-nets.patch
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

  nativeBuildInputs = [ cmake git ];
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
