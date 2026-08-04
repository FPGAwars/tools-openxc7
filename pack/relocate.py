"""Binary relocation: executables, dynamic libraries and python deps.

Linux backend: the ELF closure is read with ``ldd`` and the binaries are
re-executed through the bundled ``ld-linux`` loader (see the wrappers in
pack.components). Darwin backend: the dylib closure + @rpath relocation
is resolved globally at the end of the flow by ``macpack.relocate_dist()``
(``macpack.py`` at the repo root), followed by the ad-hoc codesign --
signing must come after relocation.
"""

import re
import shutil
import stat
import subprocess
from pathlib import Path

import ansi

from . import DIST, BIN, LIBEXEC, LIB
from .platform import IS_DARWIN

# -- The macOS (Mach-O) packaging backend. Only imported on Darwin; the
# -- CLI shim calls macpack.relocate_dist() once, after all binaries,
# -- libraries and python files have been copied into dist/.
if IS_DARWIN:
    import macpack  # noqa: F401  (darwin relocation backend, used by the shim)


# ------------------------------------------------------------------
# -- Get the dynamic libraries the given executable file
# -- depends on
# --
# -- INPUT:
# --   * binary: Name of the executable file
# --
# -- OUTPUT:
# --   * A dictionary with the libraries and their paths
# ------------------------------------------------------------------
def get_dependencies(binary: str) -> dict:

    # -- Get the path of the binary file
    binary_path = shutil.which(binary)

    # -- Get its dependencies (running the ldd command)
    # -- The raw text output is obtained
    deps_raw = subprocess.run(["ldd", str(binary_path)],
                              capture_output=True, text=True, check=True)

    # -- Dictionary to store the dependencies
    deps = {}

    # -- Walk the output, line by line
    for line in deps_raw.stdout.splitlines():
        line = line.strip()

        # Look for the pattern: libname.so.X => /path/to/libname.so.X (0x0000...)
        match = re.search(r'(\S+)\s+=>\s+(\S+)', line)
        if match:
            # -- Store the library and its path in the dictionary
            lib_name = match.group(1)
            lib_path = match.group(2)

            # -- Special case: ld-linux-x86-64.so.2
            # -- In nix it comes with the full path in the name. We truncate
            # -- it to just the name
            if "ld-linux-x86" in lib_name:
                lib_name = Path(lib_name).name
            deps[lib_name] = lib_path

        # Special case: the dynamic loader (e.g. /lib64/ld-linux-x86-64.so.2)
        # usually appears at the end without the '=>' symbol
        elif "ld-linux" in line or "ld.so" in line:
            match_ld = re.search(r'(/[^ ]+)', line)
            if match_ld:
                ld_path = match_ld.group(1)
                ld_name = ld_path.split("/")[-1]
                deps[ld_name] = ld_path

        # Special case: linux-vdso.so.1 (has no physical path)
        elif "linux-vdso" in line:
            match_vdso = re.search(r'(\S+)', line)
            if match_vdso:
                deps[match_vdso.group(1)] = ""

    # -- Return the dictionary
    return deps


# ------------------------------------------------
# -- Copy only the given executable file,
# -- without its dependencies
# ------------------------------------------------
def copy_exec(binary: str, target_dir: str = LIBEXEC):
    # -- Get the path of the executable
    executable_path = Path(str(shutil.which(binary)))

    # -- Copy the executable to the distribution directory
    executable_target_dir = Path.cwd() / DIST / target_dir
    executable_target = executable_target_dir / binary

    # -- Mark indicating the file type
    mark = ""

    # -- If it does not exist, copy it!
    if not executable_target.exists():
        shutil.copy(executable_path, executable_target)
        # -- Mark indicating it has been copied
        mark = "✅"
    else:
        # -- If it exists, print only the name, without copying
        # -- Mark indicating it was already there
        mark = "📌"

    # -- Print name of the executable
    print(f"{ansi.GREEN}  ⚙️  Ejecutable: ",
          end='', flush=True)
    print(f"{ansi.DEFAULT}{mark}{binary}")


# ------------------------------------------------------
# -- Copy the given executable into the distribution
# -- along with ALL its libraries
# ------------------------------------------------------
def copy_with_deps(binary: str):

    # -- On macOS ldd is not used: only the executable is copied, and the
    # -- dylib closure + @rpath relocation is resolved globally at the end
    # -- with macpack.relocate_dist().
    if IS_DARWIN:
        copy_exec(binary)
        return

    # -- Copy the executable first
    copy_exec(binary)

    # -- Read the libraries the executable depends on
    executable_deps = get_dependencies(binary)

    # -- Target directory for the libraries
    libs_target_dir = Path.cwd() / DIST / LIB

    # -- Mark indicating whether the file has been copied (✅)
    # -- or it was not necessary because it was already there (📌)
    mark = ""

    # -- Copy all the dependencies of yosys
    for lib_name, libs_path in executable_deps.items():

        if libs_path != "":
            # -- Full path of the file at the target
            lib_target = libs_target_dir / Path(libs_path).name

            # -- Copy the library if it does not exist yet...
            if not lib_target.exists():
                shutil.copy(libs_path, libs_target_dir)
                # -- Mark indicating it did not exist
                mark = "✅"
            # -- It already exists. Do not copy, just report
            else:
                # -- Mark indicating it already exists
                mark = "📌"

            # -- Print name of the library
            print(f"{ansi.BLUE}  🧾 Lib: ",
                  end='', flush=True)
            print(f"{ansi.DEFAULT}{mark}{lib_name}")


# -----------------------------------------------------------
# -- Copy all the python dependencies
# --
# -- store/tabbypy3 --> dist/bin
# -- nix-python/bin/python3.12 --> dist/libexec
# -- nix-python/lib/python3.12/* --> dist/lib/python3.12/
# -----------------------------------------------------------
def copy_python():

    # --- Copy the wrapper (tabbypy3)
    # -- Linux only: tabbypy3 hardcodes the ld-linux-x86-64 loader. On
    # -- macOS the python wrapper runs the bundled python3.12.
    if not IS_DARWIN:
        src = Path.cwd() / "store" / "tabbypy3"
        dst = Path.cwd() / DIST / BIN / "tabbypy3"
        if dst.exists():
            mark = "📌"
        else:
            shutil.copy(src, dst)
            mark = "✅"
        print(f"➡️  Dep: {mark}bin/tabbypy3")

    # -- Copy the python executable
    src = Path(str(shutil.which("python3.12")))
    dst = Path.cwd() / DIST / LIBEXEC / "python3.12"
    if dst.exists():
        mark = "📌"
    else:
        shutil.copy(src, dst)
        mark = "✅"
    print(f"➡️  Dep: {mark}libexec/{src.name}")

    # -- Copy the whole python directory
    src = src.parent.parent / "lib" / "python3.12"
    dst = Path.cwd() / DIST / LIB / "python3.12"
    if dst.exists():
        mark = "📌"
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        mark = "✅"
    write_access(dst)
    print(f"➡️  Dep: {mark}lib/{src.name}/")


# ----------------------------------------------------------------
# -- Locate the nix path whose name contains the string 'text'
# -- Returns the full path
# --
# --  E.g.  nix_locate("python3.12-click-8.1.7") returns
# --       7b7509xv9aqdrayjf1fv5ialf4gbi5wd-python3.12-click-8.1.7
# -- Packages ending in "-dev" are discarded
# ------------------------------------------------------------------
def nix_locate(text: str) -> Path:

    # -- Path of the nix store
    nix_store = Path("/nix/store")

    # -- Search pattern
    pattern = f"*{text}*"

    # -- The auxiliary nix outputs that do not contain the wanted files
    # -- are discarded: "-dev" (headers) and "-dist" (sdist/wheel). On
    # -- macOS the "-dist" output tends to appear first in the glob and
    # -- used to break the copy of the python packages (it has no
    # -- site-packages/<pkg>).
    paths = [path for path in nix_store.glob(pattern)
             if path.is_dir()
             and not str(path).endswith("-dev")
             and not str(path).endswith("-dist")]

    # -- Return the first match
    return paths[0]


# -----------------------------------------------------------------------
# -- Copy a python library from nix into the distribution
# -- The package directory is copied to dist/lib/python3.12/site-packages
# --
# -- E.g. package click
# --    - Source:
# --    /nix/store/xxx-python3.12-click/lib/python3.12/site-packages/
# --    - Target:
# --      dist/lib/python3.12/site-packages
# -----------------------------------------------------------------------
def copy_python_dep(pyname: str, version: str, name: str = ""):

    if name == "":
        name = pyname

    # -- Package name (name + version)
    pack_name = f"{pyname}" if version == "" else f"{pyname}-{version}"

    # -- Locate the folder where the package lives
    pkg_dir = nix_locate(f"python3.12-{pack_name}")

    # -- Source directory
    site_pack = pkg_dir / "lib" / "python3.12" / "site-packages"
    src = site_pack / name

    # -- Target directory
    dst_site_pack = Path.cwd() / DIST / LIB / "python3.12" / "site-packages"
    dst = dst_site_pack / name

    # -- Give write permissions to the "site-packages" directory
    # -- of the distribution
    if dst_site_pack.exists():
        write_access(dst_site_pack)

    mark = ""

    if dst.exists():
        mark = "📌"
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        mark = "✅"

    print(f"➡️  Dep: {mark}{pack_name}")


# ------------------------------------
# -- Run the command "file -b <path>"
# -- The processed, lowercased string
# -- is returned
# -------------------------------------
def cmd_file(path: Path) -> str:

    # -- Run "file -b <path>"
    result = subprocess.run(
        ['file', '-b', path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True
    )

    # -- Get the raw output
    output_cmd = result.stdout.strip()

    # -- Lowercase it
    output_cmd = output_cmd.lower()

    # -- Return result
    return output_cmd


# ----------------------------------------------------
# -- Check whether the file is an ELF executable
# -- Done by calling the "file" command
# ----------------------------------------------------
def is_elf(path: Path) -> bool:

    # -- Run the "file -b <path>" command
    # -- to learn the file type
    output = cmd_file(path)

    # -- On macOS the native executable is Mach-O (not ELF)
    if IS_DARWIN:
        return ("mach-o" in output) and ("executable" in output)

    # -- Detect the "elf" pattern
    return "elf " in output


# -----------------------------------------------------
# -- Check whether it is a PYTHON program
# -----------------------------------------------------
def is_python_script(path: Path) -> bool:

    # -- Run the "file -b <path>" command
    # -- to learn the file type
    output = cmd_file(path)

    # -- Detect whether it is a python script
    return "python script" in output


# -----------------------------------------------------
# -- Check whether it is a shell script
# -----------------------------------------------------
def is_shell_script(path: Path) -> bool:

    # -- Run the "file -b <path>" command
    # -- to learn the file type
    output = cmd_file(path)

    # -- Detect whether it is a shell script
    return ("bash script" in output) or ("bash -e script" in output)


# -----------------------------------------
# --  Add a shebang to a python file
# -----------------------------------------
def python_shebang_add(file_path: Path):

    try:
        # -- Read python file
        contents = file_path.read_text(encoding="utf-8")

        # -- Shebang to add
        shebang = "#!/usr/bin/env python3\n"

        # -- Add shebang!
        contents = shebang + contents

        # -- Write new contents
        file_path.write_text(contents, encoding="utf-8")
        # print(f"✔️ Shebang añadido con éxito a: {file_path}")

    except PermissionError:
        print(f"❌ Error: Sin permisos '{file_path}'.")
    except Exception as e:
        print(f"❌ Ocurrió un error inesperado: {e}")


# -----------------------------------------
# -- Add a shebang to a bash file
# -----------------------------------------
def bash_shebang_add(file_path: Path):

    try:
        # -- Read bash file
        contents = file_path.read_text(encoding="utf-8")

        # -- Shebang to add
        shebang = "#!/usr/bin/env bash\n"

        # -- Add shebang!
        contents = shebang + contents

        # -- Write new contents
        file_path.write_text(contents, encoding="utf-8")
        # print(f"✔️ Shebang añadido con éxito a: {file_path}")

    except PermissionError:
        print(f"❌ Error: Sin permisos '{file_path}'.")
    except Exception as e:
        print(f"❌ Ocurrió un error inesperado: {e}")


# -----------------------------------------
# -- Give write permissions to the file
# -----------------------------------------
def write_access(file_path: Path):

    try:
        # Get the permissions
        permissions = file_path.stat().st_mode

        # Enable write permission
        permissions = permissions | stat.S_IWUSR

        # Apply the changes
        file_path.chmod(permissions)
        # print(f"✔️ Permiso de escritura añadido a: {file_path}")

    except PermissionError:
        print("❌ Error: No tienes permiso")
