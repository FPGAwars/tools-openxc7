# Reproducible assembly of the Windows tools tree, cross-built from
# x86_64-linux with pkgsCross.mingwW64. Build with:
#   nix build .#packages.x86_64-linux.openxc7-windows-amd64-tools
#
# CI: test.yaml compiles the passthru outputs on every push; the package is
# assembled and validated by windows-package.yml (dispatch, or called by
# build-pre-release.yaml).
#
# The .exe is the himbaechel xilinx uarch, installed as nextpnr-xilinx.exe
# (the name apio runs; the engine is named in XILINX-PARTS-INDEX.json).
# Metrics come from --report, so the binary is built without an embedded
# Python interpreter: no cross CPython, no libpython, no stdlib next to the
# exe. fasm2frames still runs under the Windows python apio already has
# (oss-cad-suite), from libexec/, the same as before.
#
# The result ($out) is a chipdb-less tools tree. CI injects the verified bins
# from the chipdb job before producing the dated package tarball. This reuses
# the flake's native derivations for prjxray-db data and fasm/prjxray Python;
# only the native .exe come from the mingw cross here.
{ pkgs
, lib
, nextpnr-xilinx           # native: source revision and the prjxray-db derivation
, prjxray                  # native: provides prjxray python + fasm2frames/bit2fasm
, fasm                     # native python package (pulls textx -> arpeggio)
}:

let
  # mingw cross set, re-imported with allowUnsupportedSystem so the conservative
  # meta.platforms of header-only deps (eigen) don't block the cross eval.
  cross = import pkgs.path {
    localSystem = pkgs.system;
    crossSystem = pkgs.lib.systems.examples.mingwW64;
    config.allowUnsupportedSystem = true;
  };
  python = pkgs.python3;       # native interpreter, runs build-time scripts
  prjxrayDb = nextpnr-xilinx.prjxray-db;

  # -- Sources come from the native derivations, never re-declared here.
  nextpnrSrc = nextpnr-xilinx.src;
  prjxraySrc = prjxray.src;

  # 8 hex digits, same stamp as the native derivation: what `git describe
  # --always` prints for this revision, so --version reads the same on
  # every platform.
  gitVersion = lib.substring 0 8 nextpnr-xilinx.src.rev;

  commonFlags = [
    "-DARCH=himbaechel"
    "-DHIMBAECHEL_UARCH=xilinx"
    # No device: the chipdb bins are built on Linux and injected later.
    # The uarch's CMakeLists still requires the database path to configure.
    "-DHIMBAECHEL_XILINX_DEVICES="
    "-DHIMBAECHEL_PRJXRAY_DB=${prjxrayDb}"
    "-DBUILD_GUI=OFF" "-DBUILD_TESTS=OFF" "-DUSE_OPENMP=OFF"
    "-Wno-deprecated"
    "-DCURRENT_GIT_VERSION=${gitVersion}"
    "-DPython3_EXECUTABLE=${python.interpreter}"
  ];

  # boost without Python (the exe does not embed an interpreter) and without
  # zstd (zstd-mingw -> gnugrep -> bash-mingw doesn't cross). mingw pthreads:
  # boost::thread's headers include <pthread.h>.
  boostWin = (cross.boost.override { enablePython = false; }).overrideAttrs (o: {
    buildInputs =
      (builtins.filter (x: !(lib.hasInfix "zstd" (x.name or ""))) (o.buildInputs or []))
      ++ [ cross.windows.mingw_w64_pthreads ];
  });

  # Cross builds cannot run the bbasm they would compile. CMake includes a
  # native export unconditionally whenever CMAKE_CROSSCOMPILING is set
  # (cmake/../CMakeLists.txt, BBA_IMPORT), even when the device list is
  # empty and nothing invokes bbasm. The native tool is that import and
  # nothing else.
  bba = pkgs.stdenv.mkDerivation {
    pname = "nextpnr-xilinx-bbasm-native"; version = "unstable-2026-09-22";
    src = nextpnrSrc;
    nativeBuildInputs = [ pkgs.cmake pkgs.git pkgs.pkg-config python ];
    buildInputs = [ pkgs.boost pkgs.eigen ];
    cmakeFlags = commonFlags ++ [ "-DBUILD_PYTHON=OFF" ];
    buildFlags = [ "bbasm" ];
    installPhase = ''
      bb=$(find . -type f -name bbasm -perm -111 | head -1)
      test -n "$bb"
      test -f bba-export.cmake
      mkdir -p $out/bin
      cp "$bb" $out/bin/bbasm
      cp bba-export.cmake $out/bba-export.cmake
      chmod u+w $out/bba-export.cmake
      # The export records the build-directory path. Point it at the
      # installed binary, which is what the cross configure will import.
      sed -i "s|\"[^\"]*bbasm\"|\"$out/bin/bbasm\"|" $out/bba-export.cmake
      grep -q "\"$out/bin/bbasm\"" $out/bba-export.cmake || {
        echo "bba-export.cmake did not record the installed bbasm"
        cat $out/bba-export.cmake
        exit 1
      }
    '';
  };

  nextpnrWin = cross.stdenv.mkDerivation {
    pname = "nextpnr-xilinx-win"; version = "unstable-2026-09-22";
    src = nextpnrSrc;
    nativeBuildInputs = [ pkgs.cmake pkgs.git pkgs.pkg-config python ];
    # boost_iostreams is built against zlib, bzip2 and lzma. The embedded
    # interpreter used to pull those onto the link path; without it they
    # have to be named.
    buildInputs = [
      boostWin cross.eigen cross.windows.mingw_w64_pthreads
      cross.zlib cross.bzip2 cross.xz
    ];
    enableParallelBuilding = true;
    postPatch = ''
      # The mingw crash of the nextpnr-xilinx fork was a flat_map whose
      # ordering broke under this compiler (bound_nets). This tree's
      # router does not use that container. Pip data is handed out by
      # const reference (the old by-value copy read off the end of the
      # file mapping). Fail the build if a bump brings either back,
      # instead of shipping an .exe that dies under wine.
      if grep -n flat_map common/route/router2.cc | grep -v '#include'; then
        echo "router2 uses flat_map; that container broke routing under mingw"
        exit 1
      fi
      grep -q 'inline const PipDataPOD &chip_pip_info' himbaechel/arch.h \
        || { echo "chipdb pip info is no longer a const reference"; exit 1; }
    '';
    cmakeFlags = commonFlags ++ [
      "-DBUILD_PYTHON=OFF"
      "-DBBA_IMPORT=${bba}/bba-export.cmake"
      # IPO defaults on. mingw's lto1 dies partitioning this binary
      # (add_symbol_to_partition_1) and, when it does get through, emits
      # boost::wrapexcept's destructor once per translation unit as a
      # strong symbol. The native build keeps IPO. Windows does not.
      "-DUSE_IPO=OFF"
    ];
    installPhase = ''
      mkdir -p $out/bin
      test -f nextpnr-himbaechel.exe || {
        echo "nextpnr-himbaechel.exe was not produced"
        find . -name '*.exe' | head
        exit 1
      }
      cp nextpnr-himbaechel.exe $out/bin/nextpnr-xilinx.exe
    '';
    dontStrip = true;
  };

  prjxrayWin = cross.stdenv.mkDerivation {
    pname = "prjxray-win"; version = "9346969e";
    src = prjxraySrc;
    nativeBuildInputs = [ pkgs.cmake pkgs.git pkgs.pkg-config python ];
    buildInputs = [ boostWin cross.eigen cross.windows.mingw_w64_pthreads ];
    enableParallelBuilding = true;
    # The Win32 ports (MemoryMappedFile, Database segbits) and the ODR fix for
    # the Configuration explicit specializations used to be applied here; they
    # are upstream since openXC7/prjxray#5, so only the deprecated-warning
    # suppression from nix/prjxray.nix remains.
    postPatch = ''
      sed -i '29 itarget_compile_options(libprjxray PUBLIC "-Wno-deprecated")' lib/CMakeLists.txt || true
    '';
    cmakeFlags = [
      "-DCMAKE_BUILD_TYPE=Release" "-Wno-deprecated"
      "-DPython3_EXECUTABLE=${python.interpreter}"
    ];
    installPhase = ''
      mkdir -p $out/bin
      for t in xc7frames2bit bitread xc7patch; do
        cp "$(find . -name "$t.exe" | head -1)" $out/bin/
      done
      test -f $out/bin/xc7frames2bit.exe
    '';
    dontStrip = true;
  };

  # families and parts to ship, from the shared manifest (same list as pack/)
  chipdbManifest = builtins.fromJSON (builtins.readFile ../../chipdb-parts.json);
  chipdbFamilies = builtins.attrNames chipdbManifest;
  gccLib = "${cross.stdenv.cc.cc.lib}/x86_64-w64-mingw32/lib";

  # pure-python tool env (fasm pulls textx -> arpeggio; + prjxray's python deps).
  # withPackages keeps the *.dist-info metadata (textX needs version("textx")).
  # This is the TOOLS python (3.12) that fasm2frames imports. It is not an
  # interpreter embedded in nextpnr.
  pyEnv = python.withPackages (ps: [
    fasm ps.simplejson ps.intervaltree ps.sortedcontainers ps.pyyaml
  ]);

  cmdLauncher = name: ''
    printf '@echo off\r\nset "PKG=%%~dp0.."\r\nset "PYTHONPATH=%%PKG%%\\lib\\python3.12\\site-packages;%%PYTHONPATH%%"\r\npython "%%PKG%%\\libexec\\${name}" %%*\r\n' > $out/bin/${name}.cmd
  '';

in pkgs.runCommand "apio-openxc7-windows-amd64-tools" {
  # The cross-compiled binaries are exposed separately so the per-commit test
  # workflow can isolate nextpnr and prjxray compilation failures.
  # test.yaml builds .nextpnr and .prjxray; those names stay.
  passthru = { nextpnr = nextpnrWin; prjxray = prjxrayWin; };
} ''
  mkdir -p $out/bin $out/libexec
  mkdir -p $out/share/nextpnr/external/prjxray-db $out/lib/python3.12/site-packages

  # -- native Windows executables
  cp -L ${nextpnrWin}/bin/*.exe $out/bin/
  cp -L ${prjxrayWin}/bin/*.exe $out/bin/
  test -f $out/bin/nextpnr-xilinx.exe

  # -- runtime DLLs next to the exes (Windows searches the app dir first).
  # No libpython: the exe does not embed an interpreter.
  cp -L ${gccLib}/libstdc++-6.dll ${gccLib}/libgcc_s_seh-1.dll $out/bin/
  cp -L ${cross.windows.mingw_w64_pthreads}/bin/libwinpthread-1.dll $out/bin/
  cp -L ${cross.windows.mcfgthreads}/bin/libmcfgthread-1.dll $out/bin/
  test ! -e $out/bin/libpython3.11.dll
  test ! -e $out/lib/python3.11

  # -- xc7pll (stdlib python). Shipped in libexec + .cmd launcher like
  # -- fasm2frames/bit2fasm: a bare shebang script in bin/ does not launch
  # -- from CMD/PowerShell (apio#914) — the launcher runs it under the
  # -- Windows python already on apio's PATH (oss-cad-suite's, the same
  # -- one the xilinx build flow uses for fasm2frames).
  cp ${../../xc7pll} $out/libexec/xc7pll
  chmod u+w $out/libexec/xc7pll

  # -- shared data (chipdb bins are injected later by CI). The native
  # -- output only symlinks the database; copy the files themselves.
  ${lib.concatMapStringsSep "\n  " (family:
      "cp -aL ${prjxrayDb}/${family} $out/share/nextpnr/external/prjxray-db/")
      chipdbFamilies}
  test ! -e $out/share/nextpnr/python
  # spartan7 in this database has no settings.sh (artix7 and zynq7 do).
  # The family directory itself is what fasm2frames needs.
  for family in ${lib.concatStringsSep " " chipdbFamilies}; do
    test -d "$out/share/nextpnr/external/prjxray-db/$family"
  done

  # -- pure-python tools (strip native extensions -> Windows uses textX fallback)
  # dirs/files copied from the store come read-only -> chmod, or the find
  # -delete and the parser rewrite fail.
  # -rL: pyEnv is a python.withPackages SYMLINK forest -- a plain cp -r
  # copies the per-package links pointing into the read-only store, so
  # (a) the find -delete below never actually stripped the native .so's
  # (find does not descend into symlinked dirs; the dead linux binaries
  # rode along dereferenced at tar time) and (b) the fasm parser patch
  # below dies with EACCES writing through the link (CI 2026-08-08).
  cp -rL ${pyEnv}/lib/python3.12/site-packages/. $out/lib/python3.12/site-packages/
  chmod -R u+w $out/lib/python3.12/site-packages
  find $out/lib/python3.12/site-packages \
       \( -name '*.so' -o -name '*.dylib' -o -name '*.pyd' -o -name 'libparse_fasm*' \) -delete
  leftover=$(find $out/lib/python3.12/site-packages \( -name '*.so' -o -name '*.pyd' \) -print -quit)
  [ -z "$leftover" ] || { echo "native extension survived the strip: $leftover"; exit 1; }
  # -- With the antlr natives gone, fasm's parser __init__ would emit a
  # -- RuntimeWarning on EVERY fasm2frames run (apio#913). textX is the
  # -- INTENDED parser on Windows (the antlr extension is not cross-built;
  # -- PyPI fasm wheels stop at cp39, useless for this 3.12): import it
  # -- directly. The assert fails the build if upstream's file drifts.
  ${pyEnv}/bin/python3 - <<PYEOF
p = "$out/lib/python3.12/site-packages/fasm/parser/__init__.py"
s = open(p).read()
assert "from fasm.parser.antlr import" in s, "fasm parser __init__ drifted"
start = s.index("try:")
end = s.index("# The textx parser is available as a fallback.")
new = (
    "# openxc7 windows package: the antlr native extension is not\n"
    "# cross-built for mingw, so textX is the INTENDED parser here.\n"
    "# Import it directly -- the upstream try/except emitted a\n"
    "# RuntimeWarning on every fasm2frames run (apio#913).\n"
    "from fasm.parser.textx import parse_fasm_filename, parse_fasm_string, implementation  # noqa: E501\n\n"
)
open(p, "w").write(s[:start] + new + s[end:])
print("fasm parser: antlr fallback warning silenced (textX direct)")
PYEOF
  # prjxray python module + the python tool scripts
  cp -r ${prjxray}/usr/share/python3/prjxray $out/lib/python3.12/site-packages/
  chmod -R u+w $out/lib/python3.12/site-packages/prjxray
  cp ${prjxray}/bin/fasm2frames ${prjxray}/bin/bit2fasm $out/libexec/
  chmod u+w $out/libexec/fasm2frames $out/libexec/bit2fasm
  # The Windows fixes to the python tools (fasm2frames defaulting to
  # sys.stdout instead of /dev/stdout, bit2fasm closing its temporary file
  # before bitread writes it, and OpenSafeFile working without fcntl) are
  # upstream since openXC7/prjxray#5.
  grep -q "args.fn_out else sys.stdout" $out/libexec/fasm2frames || { echo "upstream fasm2frames fix missing"; exit 1; }
  grep -q "delete=False" $out/libexec/bit2fasm || { echo "upstream bit2fasm fix missing"; exit 1; }
  grep -q "fcntl = None" $out/lib/python3.12/site-packages/prjxray/util.py || { echo "upstream util.py fcntl guard missing"; exit 1; }

  # -- Windows launchers (apio/oss-cad-suite provides the Windows python)
  ${cmdLauncher "fasm2frames"}
  ${cmdLauncher "bit2fasm"}
  ${cmdLauncher "xc7pll"}

  chmod -R u+w $out
''
