{ stdenv, lib, fetchFromGitHub, cmake, git, python312Packages, eigen, python312
, ... }:
stdenv.mkDerivation rec {
  pname = "prjxray";
  version = "78d98b98dc189a89cd1def61cee7c938f51bc6e5";

  # openXC7/prjxray: a fork of jrrk2/prjxray (itself f4pga plus modern-gcc
  # build fixes, a gflags bump and the openxc7 fasm submodule) that now also
  # carries the Windows/ODR work we used to patch in locally — merged upstream
  # 2026-08-02 as PR #5. A strict superset of the previous jrrk2 pin.
  src = fetchFromGitHub {
    owner = "openXC7";
    repo = "prjxray";
    rev = "78d98b98dc189a89cd1def61cee7c938f51bc6e5";
    fetchSubmodules = true;
    hash = "sha256-KrPYNm8ooh49WGiJOqZD1dYgptUYNRP/jKU9C4gvgiw=";
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
