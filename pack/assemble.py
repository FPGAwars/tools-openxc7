"""Final assembly: dist/ tree init, env/VERSION files and the tarball."""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import ansi

from .components import copy_file
from .platform import plat_token


# ----------------------------------------------------------
# -- Initialize the distribution
# --
# -- Create the initial directory structure
# --
#    dist
#    |
#    +-- bin  --> Wrappers for the binaries
#    +-- libexec --> Executables (elf, bash shell, python)
#    +-- lib     --> Dynamic libraries
#    +-- chipdb  --> binary database
# ----------------------------------------------------------
def distribution_init():
    # -- Base directory of the distribution
    base_dir = Path.cwd() / "dist"

    # -- A dist/ from a previous run is NOT reusable: the copy phases skip
    # -- the files that already exist, so an old dist/ freezes binaries
    # -- from earlier builds into the package (release 2026-07-16 shipped
    # -- an unpatched nextpnr on all 3 platforms because of this).
    # -- Everything is deleted EXCEPT dist/chipdb: the .bin are expensive
    # -- to regenerate, they are platform-independent and they have their
    # -- own refresh mechanism (explicit deletion + OPENXC7_CHIPDB_SEED).
    if base_dir.exists():
        print("➡️  Limpiando dist/ anterior (se conserva dist/chipdb)...")
        subprocess.run(["chmod", "-R", "+w", str(base_dir)],
                       check=True, capture_output=True, text=True)
        for entry in base_dir.iterdir():
            if entry.name == "chipdb":
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    # -- Create the structure
    (base_dir / "bin").mkdir(parents=True, exist_ok=True)
    (base_dir / "lib").mkdir(parents=True, exist_ok=True)
    (base_dir / "libexec").mkdir(parents=True, exist_ok=True)
    (base_dir / "chipdb").mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------
# -- Final configuration
# -- * Copy the environment file into the root of the
# -- distribution
# ------------------------------------------------------
def write_env():
    # -- Final configuration
    print()
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  CONFIGURACION FINAL")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print()

    # -- Include the environment file
    # -- config/environment --> dist
    src = Path.cwd() / "config/environment"
    dst = Path.cwd() / "dist"
    msg = copy_file(src, dst)
    print(msg)
    print()

    # -- Ecosystem convention: every apio package carries a BUILD-INFO.json
    # -- at its root. CI composes it (scripts/build-info.sh) and points
    # -- OPENXC7_BUILD_INFO at it; a local build without the variable
    # -- simply ships without the file.
    build_info = os.environ.get("OPENXC7_BUILD_INFO")
    if build_info:
        shutil.copy(build_info, dst / "BUILD-INFO.json")
        print(f"🔵 ✅BUILD-INFO.json ({build_info})")
        print()

    # -- The public release index is dated, but its name inside every package
    # -- is stable so apio can locate it without deriving the release date.
    chipdb_index = os.environ.get("OPENXC7_CHIPDB_INDEX")
    if chipdb_index:
        shutil.copy(chipdb_index, dst / "apio-xilinx-chipdb-index.json")
        print(f"🔵 ✅apio-xilinx-chipdb-index.json ({chipdb_index})")
        print()


# -----------------------------------
# -- Return the current date in
# -- year-month-day format
# --
# -- E.g. "20260526"
# ------------------------------------
def get_date() -> str:

    # -- Allow fixing the date from outside (CI) so that the package name
    # -- and the VERSION match the release tag on every runner. Accepts
    # -- YYYYMMDD or YYYY-MM-DD. Without the variable -> today's date.
    override = os.environ.get("OPENXC7_PACK_DATE")
    if override:
        return override.replace("-", "")

    now = datetime.now()

    # -- Format to use
    # %Y = 4-digit year (e.g. 2026)
    # %m = 2-digit month (e.g. 05)
    # %d = 2-digit day of the month (e.g. 26)
    date = now.strftime("%Y%m%d")

    return date


# --------------------------------------------------
# -- Generate the file with the version, which is
# -- copied into the distribution
# -- Returns the text with the version
# --------------------------------------------------
def write_version() -> str:
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  GENERANDO LA VERSION")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print()

    date = get_date()
    version_file = Path("dist/VERSION")
    version_file.write_text(date, encoding="utf-8")
    print(f"🏷️  Version: {date}")
    print(f"🔵 Fichero: ✅{version_file.name}")
    print()

    # -- Return string with the version
    return date


# ----------------------------------------------------
# -- Build the .tgz file with the distribution
# --
# -- tools-openxc7-linux-x64-version.tgz
# ----------------------------------------------------
def build_tarball(version: str):

    # -- Generate tarball
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  GENERANDO TARBALL")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print()

    # -- Package name (per OS/arch; on Linux x86_64 -> identical to the
    # -- historic 'apio-openxc7-linux-x86-64-<date>.tgz')
    tarball_name = Path(f"apio-openxc7-{plat_token()}-{version}.tgz")

    # -- Before compressing we give write permissions to ALL the
    # -- files and directories
    print("➡️  Dando permisos de escritura...")
    cmd = ["chmod", "-R", "+w", "dist"]
    subprocess.run(cmd,
                   check=True,
                   capture_output=True,
                   text=True)

    # -- Compress by calling tar in the shell.
    # -- COPYFILE_DISABLE=1 keeps the macOS tar from including AppleDouble
    # -- '._*' files with the metadata/xattrs (harmless on Linux).
    print(f"➡️  {tarball_name}")
    print("⏳ Comprimiendo...")
    # cmd = ["tar", "-czf", f"{tarball_name}",
    #        "--transform=s|^dist|openxc7|", "dist/"]
    # -- tar -czf hola.tgz -C dist/ .
    cmd = ["tar", "-czf", f"{tarball_name}", "-C", "dist/", "."]
    subprocess.run(cmd,
                   check=True,
                   capture_output=True,
                   text=True,
                   env=dict(os.environ, COPYFILE_DISABLE="1"))

    # -- Show the tarball name to the user
    print(f"🔵 ✅{tarball_name}")
    print()
