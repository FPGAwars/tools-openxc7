{ stdenv, lib, nextpnr-xilinx, prjxray-db, python312
, die            # e.g. xc7a50t: the fabric the chipdb describes
, family         # its prjxray-db directory, e.g. artix7
, ... }:

# One chipdb file of the himbaechel xilinx uarch: chipdb-<die>.bin, the
# database every part of that die routes with (xc7a35t parts use the
# xc7a50t one). The same two commands pack/chipdb.py runs -- the
# generator of the nextpnr source tree, then that build's bbasm -- for the
# consumers that want the chipdb as a store path (the docker image).
stdenv.mkDerivation {
  pname = "nextpnr-xilinx-chipdb-${die}";
  inherit (nextpnr-xilinx) version;

  dontUnpack = true;
  nativeBuildInputs = [ python312 nextpnr-xilinx ];

  buildPhase = ''
    runHook preBuild
    python3.12 ${nextpnr-xilinx.chipdbGenerator} \
      --xray ${prjxray-db}/${family} --device ${die} --bba chipdb-${die}.bba
    bbasm --le chipdb-${die}.bba chipdb-${die}.bin
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm644 chipdb-${die}.bin $out/chipdb-${die}.bin
    runHook postInstall
  '';

  meta = {
    description = "nextpnr chipdb of the ${die} die (himbaechel xilinx uarch)";
    platforms = lib.platforms.all;
  };
}
