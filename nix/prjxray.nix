{ stdenv, lib, fetchFromGitHub, cmake, git, python312Packages, eigen, python312
, ... }:
stdenv.mkDerivation rec {
  pname = "prjxray";
  version = "ef5203e9d06e9ffda79168439723579217ca8110";

  # openXC7/prjxray master 2026-08-18: on top of the previous revision (our
  # Windows/ODR work, PR #5) it carries our bitread use-after-free fix (PR #6:
  # bit2fasm works again), the OSERDES DATA_WIDTH 10/14 fuzzing, and regymm's
  # Zynq 7030/7035/7045/7100 support.
  src = fetchFromGitHub {
    owner = "openXC7";
    repo = "prjxray";
    rev = "ef5203e9d06e9ffda79168439723579217ca8110";
    fetchSubmodules = true;
    hash = "sha256-lSj5bMPbLPD3Eu8ZZlebA0K14w9XelBAWqFbWRB77t4=";
  };

  nativeBuildInputs = [ cmake git ];
  buildInputs = [ python312Packages.boost python312 eigen ];

  patchPhase = ''
    sed -i 's/cmake /cmake -Wno-deprecated /g' Makefile
    sed -i '29 itarget_compile_options(libprjxray PUBLIC "-Wno-deprecated")' lib/CMakeLists.txt
  '';

  installPhase = ''
    mkdir -p $out/bin
    cp -v tools/xc7frames2bit tools/bitread tools/xc7patch $out/bin
    cp -v $srcs/utils/fasm2frames.py $out/bin/fasm2frames
    chmod 755 $out/bin/fasm2frames
    cp -v $srcs/utils/bit2fasm.py $out/bin/bit2fasm
    chmod 755 $out/bin/bit2fasm
    mkdir -p $out/usr/share/python3/
    cp -rv $srcs/prjxray $out/usr/share/python3/
  '';

  doCheck = false;

  meta = with lib; {
    description = "Xilinx series 7 FPGA bitstream documentation";
    homepage = "https://github.com/jrrk2/prjxray";
    license = licenses.isc;
    platforms = platforms.all;
  };
}
