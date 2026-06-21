# Assemble the native-binary part of the apio-openxc7-windows-amd64 package:
# the cross-built Windows .exe + their runtime DLLs (next to the exes; Windows
# searches the application directory first -> no rpath/codesign needed),
# the chipdb, prjxray-db and nextpnr python. The pure-python tools (fasm,
# textx, prjxray, fasm2frames) are platform-independent and added separately.
let
  pkgs       = import ./nixpkgs-src {};
  nextpnrWin = import ./mingw-spike.nix;     # nextpnr-xilinx.exe (std::map fix)
  prjxrayWin = import ./prjxray-mingw.nix;   # xc7frames2bit/bitread/xc7patch.exe
  src        = ./nextpnr-src;
  chipdb     = ./e2e/xc7a35tcpg236.bin;      # platform-independent .bin
in pkgs.runCommand "openxc7-windows-tree" { } ''
  mkdir -p $out/bin $out/chipdb
  mkdir -p $out/share/nextpnr/external/prjxray-db $out/share/nextpnr/python

  # -- native Windows executables
  cp ${nextpnrWin}/bin/*.exe $out/bin/
  cp ${prjxrayWin}/bin/xc7frames2bit.exe ${prjxrayWin}/bin/bitread.exe \
     ${prjxrayWin}/bin/xc7patch.exe $out/bin/

  # -- runtime DLLs next to the exes (deref the nix symlinks)
  for d in ${nextpnrWin}/bin/*.dll ${prjxrayWin}/bin/*.dll; do
    [ -e "$d" ] && cp -Lf "$d" $out/bin/ || true
  done
  chmod -R u+w $out/bin

  # -- chipdb (xc7a35tcpg236) + data
  cp ${chipdb} $out/chipdb/xc7a35tcpg236.bin
  cp -r ${src}/xilinx/external/prjxray-db/artix7 $out/share/nextpnr/external/prjxray-db/
  cp -r ${src}/xilinx/python/. $out/share/nextpnr/python/
  chmod -R u+w $out/share

  echo "=== bin ==="; ls $out/bin
  echo "=== tree ==="; find $out -maxdepth 3 -type d | sort
''
