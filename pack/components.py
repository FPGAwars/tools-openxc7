"""Per-tool packaging phases.

Phase 1 copies each tool's executables and libraries, phase 2 generates
their bin/ wrappers, and the phase-3 functions copy the data specific to
each tool (yosys, nextpnr-xilinx, fasm, prjxray).
"""

import shutil
import stat
import subprocess
from pathlib import Path

import ansi

from . import DIST, BIN, LIBEXEC, LIB
from .families import families
from .platform import IS_DARWIN
from .relocate import (
    bash_shebang_add,
    copy_exec,
    copy_python,
    copy_python_dep,
    copy_with_deps,
    is_elf,
    is_python_script,
    is_shell_script,
    nix_locate,
    python_shebang_add,
    write_access,
)


class ToolWrapper:

    # -- Header of the shell wrapper, common to all wrappers
    BIN_WRAPPER = """\
#!/usr/bin/env bash\n
release_bindir="$(dirname "${BASH_SOURCE[0]}")"
release_bindir_abs="$(readlink -f "$release_bindir")"
release_topdir_abs="$(readlink -f "$release_bindir/..")"
export PATH="$release_bindir_abs:$PATH"
"""

    # -- Header for macOS: 'readlink -f' is not portable on BSD; 'cd ... &&
    # -- pwd' is used instead, which resolves the absolute path without
    # -- depending on GNU coreutils or on DYLD_* (which SIP strips).
    MAC_WRAPPER = """\
#!/usr/bin/env bash\n
release_bindir_abs="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
release_topdir_abs="$(cd "$release_bindir_abs/.." && pwd)"
export PATH="$release_bindir_abs:$PATH"
"""

    def __init__(self, bin_name: str):

        # -- Save the binary name
        self.bin = bin_name

        # -- Shell: content of the wrapper (header depends on the platform)
        self.shell = self.MAC_WRAPPER if IS_DARWIN else self.BIN_WRAPPER

        # -- Save the full path
        self.path = Path.cwd() / DIST / BIN / self.bin

    # -- Add debug traces
    def add_debug(self):
        self.shell += 'echo Bindir: ${release_bindir}\n'
        self.shell += 'echo Bindir_abs: ${release_bindir_abs}\n'
        self.shell += 'echo Topdir_abs: ${release_topdir_abs}\n'

    def add_exec_python(self):
        if IS_DARWIN:
            # -- macOS: run the bundled python3.12 directly.
            # -- tabbypy3 hardcodes the ld-linux loader and is useless here.
            self.shell += 'export PYTHONHOME="$release_topdir_abs"\n'\
                          'exec "$release_topdir_abs"/libexec/python3.12 '\
                          f'"$release_topdir_abs"/libexec/{self.bin} "$@"\n'
            return
        self.shell += 'export PYTHONEXECUTABLE='\
                      '"$release_bindir_abs/tabbypy3"\n'\
                      'exec "$release_bindir_abs/tabbypy3" '\
                      f'"$release_topdir_abs"/libexec/{self.bin} "$@"\n'

    def add_exec(self):
        if IS_DARWIN:
            # -- macOS: the @rpath/@loader_path are baked into the Mach-O
            # -- (macpack.relocate_dist), so just exec it. Neither the
            # -- dynamic loader nor DYLD_* (SIP strips them) are used.
            self.shell += 'exec "$release_topdir_abs"/libexec/'\
                          f'{self.bin} "$@"\n'
            return
        self.shell += 'exec "$release_topdir_abs"/lib/ld-linux-x86-64.so.2 '\
                      '--inhibit-cache '\
                      '--inhibit-rpath "" '\
                      '--library-path "$release_topdir_abs"/lib '\
                      f'"$release_topdir_abs"/libexec/{self.bin} "$@"\n'

    # -- Return the full path of the wrapper
    def get_path(self) -> Path:
        return self.path

    def write_bin(self):

        # -- Get the path where the wrapper is written
        wrapper_file = self.path

        try:
            wrapper_file.write_text(self.shell, encoding="utf-8")

        except PermissionError:
            print(f"❌ Error: sin permisos '{self.bin}'.")
        except FileNotFoundError:
            print("❌ Directorio no existe")
        except Exception as e:
            print(f"❌ Error inesperado al escribir el archivo: {e}")

        # -- Give execution permissions
        wrapper_file.chmod(wrapper_file.stat().st_mode | stat.S_IXUSR)


# ------------------------------------------------------
# -- Every tool has several executable files
# -- that are copied to libexec
# --
# -- If the executable is an ELF, all the dynamic
# -- libraries it depends on are analyzed and copied
# -- into lib
# --
# -- If the executable is a python one, a shebang is
# -- added and it is copied into libexec
# --
# -- If the executable is a shell script, a shebang is
# -- added and it is copied into bin
# --------------------------------------------------------
def run_phase1(name: str):
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 1: Ejecutables y bibliotecas")
    print(ansi.DEFAULT, end='')
    print()

    # -- Get the path of the executable
    executable_path = Path(str(shutil.which(name)))

    # -- Get its directory
    executable_path_dir = executable_path.parent

    # -- Read all the files in that directory
    list_exec = [entry for entry in executable_path_dir.iterdir()
                 if entry.is_file()]

    # -- Walk all the files
    for entry in list_exec:

        # -- Report the current file
        print(f"🔵 {entry.name}", end='')

        # -- It is an EXECUTABLE
        if is_elf(entry):

            print("(ELF)")

            # -- Copy it into the distribution
            # -- along with all its libraries
            copy_with_deps(entry.name)

        # -- It is a Python script
        elif is_python_script(entry):
            print("(PYTHON)")

            # -- Copy it into the distribution, as is
            copy_exec(entry.name)

            # -- Give write permissions to the python file
            python_file_path = Path.cwd() / DIST / LIBEXEC / entry.name
            write_access(python_file_path)

            # -- Add a shebang at the beginning
            python_shebang_add(python_file_path)

        # -- It is a shell script
        elif is_shell_script(entry):
            print("(SHELL)")

            # -- Copy it into the distribution, as is
            copy_exec(entry.name, BIN)

            # -- Give write permissions to the bash file
            bash_file_path = Path.cwd() / DIST / BIN / entry.name
            write_access(bash_file_path)

            # -- Add a shebang at the beginning
            bash_shebang_add(bash_file_path)

        # -- It is another kind of file
        else:
            print("(UNKNOWN)")

        print()


# -----------------------------------------------------------------
# -- Tool processing: generation of the wrappers
# --
# --  Every executable file (elf, python or shell) lives
# -- in the libexec directory, and has another executable in bin
# -- with the same name, which is where the PATH points and is
# -- therefore the one that runs: its wrapper
# --
# -- What it does is call the real executable, but
# -- setting the base directory where the libraries and data
# -- live, so that it does NOT use the system ones
# --
# -- This method would be equivalent to having static libraries
# -- but using dynamic ones
# ----------------------------------------------------------------
def run_phase2(name: str):
    print(ansi.YELLOW, end='')
    print("─────────────────────────────────────────────────────")
    print("Fase 2: Generacion de wrappers")
    print(ansi.DEFAULT, end='')
    print()

    # -- Get the path of the executable
    executable_path = Path(str(shutil.which(name)))

    # -- Get its directory
    executable_path_dir = executable_path.parent

    # -- Read all the files in that directory
    list_exec = [entry for entry in executable_path_dir.iterdir()
                 if entry.is_file()]

    mark = ""
    info = ""

    # -- Walk all the files
    for entry in list_exec:

        # -- It is an EXECUTABLE
        if is_elf(entry):

            # -- Create the wrapper
            wrapper = ToolWrapper(entry.name)
            # wrapper.add_debug()
            wrapper.add_exec()

            wrapper_path = wrapper.get_path()
            mark = "⬇️ " if wrapper_path.exists() else "✅"
            wrapper.write_bin()

            info = f"🔵 {mark}{entry.name}(ELF)"

        elif is_python_script(entry):

            # -- Create the wrapper
            wrapper = ToolWrapper(entry.name)
            # wrapper.add_debug()
            wrapper.add_exec_python()

            wrapper_path = wrapper.get_path()
            mark = "⬇️ " if wrapper_path.exists() else "✅"
            wrapper.write_bin()
            info = f"🔵 {mark}{entry.name}(PYTHON)"

        elif is_shell_script(entry):
            info = f"❌ {entry.name}(SHELL)"

        else:
            info = f"❌ {entry.name}(UNKNOWN)"

        # -- Report the current file
        print(f"{info}")


# -----------------------------------------
# -- Copy tool-specific file trees
# -----------------------------------------
def copy_tree(src: Path, dst: Path):

    mark = ""

    try:
        shutil.copytree(src, dst)  # dirs_exist_ok=True)
        write_access(dst)
        mark = "✅"

    except Exception:  # as e:
        mark = "📌"
        # print(f"❌ Error: {e}")

    finally:
        print(f"{mark} {dst.relative_to(Path.cwd())}")


# ------------------------------------------------
# -- Copy the file from the source directory
# -- to the target, if it does not exist yet
# --
# -- A string is returned with the file name
# -- and a mark indicating whether it was copied✅ or
# -- the previous version is kept 📌
# ------------------------------------------------
def copy_file(src: Path, dst: Path) -> str:

    # mark = ""

    # -- Check whether the file already exists in the
    # -- target directory
    if (dst / src.name).exists():

        # -- It already exists, report it
        mark = "📌"
    else:
        # -- It does not exist, copy it!
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            print(f"❌ Error: {e}")
        mark = "✅"

    # -- Return string
    return (f"➡️  Dep: {mark}{src.name}")


def run_phase3_yosys():
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 3: Copiar datos de yosys")
    print()
    print(ansi.DEFAULT, end='')

    # ---- Get directories
    # -- Base directory of yosys
    base_dir = Path(str(shutil.which("yosys"))).parent.parent

    # -- Copy /share/yosys
    src = base_dir / "share" / "yosys"
    dst = Path.cwd() / DIST / "share" / "yosys"
    copy_tree(src, dst)

    # -- Copy the python dependencies
    copy_python()

    # -- Copy the specific python packages
    copy_python_dep("click", "8.1.7")


def run_phase3_nextpnr_xilinx():
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 3: Copiar datos de nextpnr-xilinx")
    print()
    print(ansi.DEFAULT, end='')

    base_src_dir = Path(str(shutil.which("nextpnr-xilinx"))).parent.parent

    # -- nextpnr-xilinx-0.8.2/share/nextpnr/external/prjxray-db/<family>/
    # -- ---> dist/share/nextpnr/external/prjxray-db/<family>/
    # -- One copy per family present in the manifest (used to hardcode
    # -- artix7; identical behavior with the current artix7-only manifest)
    for family in families():
        db_dir = f"share/nextpnr/external/prjxray-db/{family}"
        src = base_src_dir / db_dir
        dst = Path.cwd() / DIST / db_dir
        copy_tree(src, dst)

    # -- nextpnr-xilinx-0.8.2/share/nextpnr/python --->
    # -- dist/share/nextpnr/python
    python_dir = "share/nextpnr/python"
    src = base_src_dir / python_dir
    dst = Path.cwd() / DIST / python_dir
    copy_tree(src, dst)

    # -- nextpnr-xilinx-0.8.2/share/nextpnr/constids.inc -->
    # -- dist/share/nextpnr
    src = base_src_dir / "share/nextpnr/constids.inc"
    dst = Path.cwd() / "dist/share/nextpnr"
    msg = copy_file(src, dst)
    print(msg)

    # -- nextpnr-xilinx-0.8.2/share/nextpnr/external/nextpnr-xilinx-meta/
    # --  <family> -->
    # -- dist/share/nextpnr/external/nextpnr-xilinx-meta/<family>
    # -- (same per-family iteration as the prjxray-db copy above)
    for family in families():
        meta_dir = f"share/nextpnr/external/nextpnr-xilinx-meta/{family}"
        src = base_src_dir / meta_dir
        dst = Path.cwd() / DIST / meta_dir
        copy_tree(src, dst)


def run_phase3_fasm():
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 3: Copiar datos de fasm")
    print()
    print(ansi.DEFAULT, end='')

    # --- Copy fasm and its dependencies
    copy_python_dep("fasm", "")
    copy_python_dep("textx", "4.0.1")

    # -- Native libraries loaded at RUNTIME via ctypes/dlopen (they are not
    # -- LC_LOAD_DYLIB/DT_NEEDED dependencies of the executables), so they
    # -- must be copied explicitly. On Linux: .so (antlr/libuuid/libffi).
    # -- On macOS: only the libffi .dylib (for _ctypes) and libantlr (for
    # -- the fast parser's libparse_fasm.dylib); libuuid is provided by
    # -- libSystem.
    dst = Path.cwd() / "dist" / "lib"
    if not IS_DARWIN:
        # -- libantlr4
        antlr_dir = nix_locate("antl")
        lib_dir = antlr_dir / "lib"
        pattern = "libantlr4-runtime.so.*"
        files = list(lib_dir.glob(pattern))
        for lib_file in files:
            msg = copy_file(lib_file, dst)
            print(msg)

        # -- libuuid.so.1 (util-linux-minimal). The version is fixed by the
        # -- the nixpkgs revision is fixed -> do not hardcode it: look for the *-lib
        # -- output that actually contains the library. (The 2.40.4
        # -- hardcode worked by accident: it was provided by CI's own nix
        # -- installer, not by the devShell.)
        candidates = sorted(
            d for d in Path("/nix/store").glob("*util-linux-minimal-*-lib")
            if (d / "lib" / "libuuid.so.1").exists())
        if not candidates:
            raise SystemExit(
                "❌ libuuid: ningun util-linux-minimal-*-lib en /nix/store")
        src = candidates[0] / "lib" / "libuuid.so.1"
        msg = copy_file(src, dst)
        print(msg)

        # -- libffi.so
        ffi_dir = nix_locate("libffi-3.4.6")
        src = ffi_dir / "lib" / "libffi.so.8"
        msg = copy_file(src, dst)
        print(msg)
    else:
        # -- libffi.*.dylib (looked up by _ctypes via @rpath -> dist/lib)
        ffi_dir = nix_locate("libffi-3.4.6")
        for f in (ffi_dir / "lib").glob("libffi.*.dylib"):
            if not f.is_symlink():
                print(copy_file(f, dst))

        # -- libantlr4-runtime.*.dylib (looked up by libparse_fasm.dylib
        # -- via @rpath)
        antlr_dir = nix_locate("antlr-runtime-cpp")
        for f in (antlr_dir / "lib").glob("libantlr4-runtime.*.dylib"):
            if not f.is_symlink():
                print(copy_file(f, dst))


def run_phase3_prjxray():
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 3: Copiar datos de prjxray")
    print()
    print(ansi.DEFAULT, end='')

    # ---- Prjxray
    # {prjxray}/usr/share/python3/prjxray -->
    # ---> dist/lib/python3.12/site-packages/prjxray
    # -- Locate the folder where the package lives
    pkg_dir = nix_locate("prjxray")
    src = pkg_dir / "usr" / "share" / "python3" / "prjxray"
    dst = Path.cwd() / DIST / LIB / "python3.12" \
        / "site-packages" / "prjxray"

    mark = ""
    if dst.exists():
        mark = "📌"
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        mark = "✅"

    print(f"➡️  Dep: {mark}prjxray")

    # -- Python packages
    copy_python_dep("pyyaml", "6.0.1", "yaml")
    copy_python_dep("simplejson", "3.19.2")
    copy_python_dep("intervaltree", "3.1.0")
    copy_python_dep("sortedcontainers", "2.4.0")

    # -- File locking: best-effort instead of fatal
    # --
    # -- OpenSafeFile is on the hot path of every build (tile.py, lib.py and
    # -- tile_segbits.py read the database through it), and upstream aborts
    # -- the whole flow when flock fails. On some network/lab filesystems it
    # -- fails with "[Errno 9] Bad file descriptor" -- originally seen on the
    # -- URJC lab machines -- so every build there died.
    # --
    # -- The old fix replaced util.py wholesale with a copy that never locked,
    # -- shipping one site's workaround to everybody. The new one keeps
    # -- upstream's locking where it works and degrades where it does not:
    # -- the packaged tools only read the database, so a failed lock is not
    # -- worth losing a build over. It warns once and carries on.
    # --
    # -- PRJXRAY_NO_FILE_LOCK=1 skips the attempt entirely, for anyone who
    # -- prefers not to pay the timeout on a filesystem known to be hostile.
    PATCH_DIR = "lib/python3.12/site-packages/prjxray"
    util_file = Path.cwd() / DIST / PATCH_DIR / "util.py"
    text = util_file.read_text()

    anchor = "from .roi import Roi\n"
    fatal = (
        "        except Exception as e:\n"
        '            print(f"{e}: {self.name}")\n'
        "            exit(1)\n"
    )
    # -- unlock_file also unlocks without protection: if flock fails on
    # -- entry, it fails again on exit and the exception kills the build in
    # -- __exit__ (caught while testing it). BOTH sites must be degraded.
    unlock = "        fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)\n"
    for chunk, what in (
        (anchor, "el ancla de imports"),
        (fatal, "el exit(1) de lock_file"),
        (unlock, "el flock de unlock_file"),
    ):
        if chunk not in text:
            raise SystemExit(
                f"❌ {PATCH_DIR}/util.py: no se encontró {what} "
                "(¿cambió el fichero upstream?)"
            )

    prelude = anchor + (
        "\n"
        "# -- openXC7 packaging: locking is best-effort.\n"
        "# -- Upstream aborts the flow when flock fails; these tools only read\n"
        "# -- the database, so on filesystems that cannot lock we warn once and\n"
        "# -- continue instead of killing the build. Set PRJXRAY_NO_FILE_LOCK=1\n"
        "# -- to skip the attempt altogether.\n"
        "_openxc7_lock_warned = False\n"
        "\n"
        "\n"
        "def _openxc7_lock_unavailable(exc, name):\n"
        "    global _openxc7_lock_warned\n"
        "    if not _openxc7_lock_warned:\n"
        "        print(f'warning: file locking unavailable ({exc}); '\n"
        "              f'continuing without it [{name}]')\n"
        "        _openxc7_lock_warned = True\n"
        "\n"
        "\n"
        'if os.environ.get("PRJXRAY_NO_FILE_LOCK"):\n'
        "    fcntl = None\n"
    )
    degraded = (
        "        except Exception as e:\n"
        "            _openxc7_lock_unavailable(e, self.name)\n"
    )
    safe_unlock = (
        "        try:\n"
        "            fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)\n"
        "        except Exception as e:\n"
        "            _openxc7_lock_unavailable(e, self.name)\n"
    )

    # -- The file copied from the nix store is read-only; on macOS write
    # -- access must be enabled before touching it (a no-op if it already
    # -- was writable).
    write_access(util_file)
    util_file.write_text(
        text.replace(anchor, prelude, 1)
        .replace(fatal, degraded, 1)
        .replace(unlock, safe_unlock, 1)
    )

    result = util_file.read_text()
    if (
        "_openxc7_lock_unavailable" not in result
        or "exit(1)" in result
        or result.count("_openxc7_lock_unavailable(e, self.name)") != 2
    ):
        raise SystemExit(f"❌ {PATCH_DIR}/util.py: el parche de locking no quedó aplicado")
    mark = "✅"
    print(f"➡️  Dep: {mark}{PATCH_DIR}/util.py (locking best-effort)")

    # -- DEBUG
    # dir = nix_locate("nextpnr-xilinx")
    # print(dir)


def process_binaries(name: str):
    print()
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print(f"  {name.capitalize()}")
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    # print()

    # -- Run phase 1: copy executables and libraries
    run_phase1(name)

    # -- Phase 2: create the wrappers for the executables
    run_phase2(name)
    print()


# -----------------------------------------------------------
# -- Get all the binaries, libraries and dependencies
# -- of ALL the tools needed to perform
# -- the synthesis
# -----------------------------------------------------------
def install_components():
    # ------ Process each one of the tools
    # ------ Copy the binaries, libraries and data
    # ------ into the distribution
    # ------ Every tool has a processing that is common
    # ------ to all of them (process_binaries), and a specific
    # ------ one (run_phase3_*())

    # -- Yosys is already in oss-cad-suite, so it is
    # -- not included in openxc7
    # -- The functions are kept for future
    # -- experiments
    # process_binaries("yosys")
    # run_phase3_yosys()

    # -- Copy the python dependencies
    print()
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print("  PYTHON dependencies")
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    copy_python()

    # -- Nextpnr-xilinx
    process_binaries("nextpnr-xilinx")
    run_phase3_nextpnr_xilinx()

    # --- fasm
    process_binaries("fasm")
    run_phase3_fasm()

    # -------- prjxray tool
    process_binaries("fasm2frames")
    run_phase3_prjxray()

    # -------- xc7pll (PLL parameter calculator; pure-stdlib python, so a
    # -------- plain `#!/usr/bin/env python3` shebang works everywhere and
    # -------- no relocation or wrapper is needed)
    print()
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print("  xc7pll")
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    dst = Path(DIST) / BIN / "xc7pll"
    shutil.copy("xc7pll", dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("  xc7pll -> bin/xc7pll")
    print()
