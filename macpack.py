"""macOS (Mach-O) packaging backend for openxc7-pack.py.

This is the macOS counterpart of the Linux ``ldd`` + wrapper +
``LD_LIBRARY_PATH`` strategy. It is only imported/used when running on
Darwin; the Linux code path in ``openxc7-pack.py`` is never touched.

Why a different strategy on macOS:
  * macOS has no ``ldd`` -> dependencies are read with ``otool -L``.
  * Shared libraries are Mach-O ``.dylib`` (not ELF ``.so``), and they
    reference their dependencies by absolute install name.
  * The Linux trick of re-exec'ing through the dynamic loader with
    ``--library-path`` does NOT port: System Integrity Protection (SIP)
    strips ``DYLD_*`` environment variables across the shell. The portable
    fix is to BAKE ``@rpath``/``@loader_path`` into every Mach-O file with
    ``install_name_tool`` and ad-hoc re-sign with ``codesign`` (mandatory on
    Apple Silicon after any Mach-O edit).

The whole approach was validated by ``spike/relocate_one.sh`` (GATE B):
nextpnr-xilinx's 25-dylib closure relocated and ran outside /nix/store.

Public entry point: ``relocate_dist(dist_dir)`` — call it once, after all
binaries/libraries/python files have been copied into ``dist/``. It:
  1. scans dist/ for every Mach-O file,
  2. pulls the transitive closure of their /nix/store dylib deps into
     dist/lib,
  3. rewrites every absolute non-system reference to ``@rpath/<basename>``,
     sets each dylib id, adds the right LC_RPATH per file depth,
  4. ad-hoc re-signs everything.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

# Library references provided by the OS itself (dyld shared cache); never
# bundled or rewritten.
SYSTEM_PREFIXES = ("/usr/lib/", "/System/")


def is_macho(path: Path) -> bool:
    """True if *path* is a Mach-O binary (executable, dylib or bundle)."""
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    # Mach-O 64-bit (LE/BE), 32-bit, and fat/universal magics.
    return magic in (
        b"\xcf\xfa\xed\xfe",  # MH_MAGIC_64
        b"\xfe\xed\xfa\xcf",  # MH_CIGAM_64
        b"\xce\xfa\xed\xfe",  # MH_MAGIC
        b"\xfe\xed\xfa\xce",  # MH_CIGAM
        b"\xca\xfe\xba\xbe",  # FAT_MAGIC (universal)
        b"\xbe\xba\xfe\xca",  # FAT_CIGAM
    )


def _is_system_ref(ref: str) -> bool:
    return ref.startswith(SYSTEM_PREFIXES)


def _otool_deps(path: Path) -> list:
    """Absolute, non-system Mach-O dynamic deps declared by *path*.

    Skips line 1 (the file's own install id) and any @rpath/@loader_path/
    @executable_path entries (already relative) and OS-provided libraries.
    """
    out = subprocess.run(
        ["otool", "-L", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout

    deps = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        m = re.match(r"(\S+)\s+\(", line)
        if not m:
            continue
        ref = m.group(1)
        if ref.startswith("@") or _is_system_ref(ref) or not ref.startswith("/"):
            continue
        deps.append(ref)
    return deps


def _make_writable(path: Path):
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _iter_macho(dist_dir: Path):
    for p in dist_dir.rglob("*"):
        if is_macho(p):
            yield p


def _bundle_roots(dist_dir: Path) -> list:
    """Mach-O files whose dependency closure we actually bundle.

    Only the real tool executables (and the bundled python interpreter) that
    live directly in dist/libexec. We deliberately do NOT seed from the
    hundreds of python C-extensions under dist/lib/python3.12: that would drag
    in tk/tcl/X11/openssl closures for extensions the toolchain never imports.
    Those extensions are still relocated (refs rewritten to @rpath) so nothing
    points at /nix/store — they just keep whatever deps are already bundled,
    exactly like the Linux package (pure-python fallbacks cover the rest).
    """
    libexec = dist_dir / "libexec"
    return [p for p in libexec.iterdir() if is_macho(p)] if libexec.is_dir() else []


def _collect_and_copy_libs(dist_dir: Path) -> None:
    """Pull the transitive closure of /nix/store dylib deps into dist/lib.

    Iterates to a fixed point: newly copied libs may themselves pull in more.
    """
    lib_dir = dist_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)

    seen = set()           # absolute source paths already processed
    copied_names = set()   # basenames present in dist/lib

    # Seed the worklist with the deps of the bundle roots only.
    work = []
    for f in _bundle_roots(dist_dir):
        work.extend(_otool_deps(f))

    while work:
        src = work.pop()
        if src in seen:
            continue
        seen.add(src)
        base = Path(src).name
        dst = lib_dir / base
        if base not in copied_names and not dst.exists():
            try:
                shutil.copy(src, dst)
                _make_writable(dst)
                copied_names.add(base)
                print(f"{'  '}🧾 dylib: ✅{base}")
            except OSError as e:
                print(f"❌ Error copiando {src}: {e}")
                continue
        # Recurse into the dependency's own deps.
        work.extend(_otool_deps(Path(src)))


def _rpath_to_lib(macho: Path, lib_dir: Path) -> str:
    """LC_RPATH value so that @rpath resolves to dist/lib from *macho*."""
    rel = os.path.relpath(lib_dir, macho.parent)
    if rel == ".":
        return "@loader_path"
    return "@loader_path/" + rel


def _existing_rpaths(path: Path) -> list:
    out = subprocess.run(
        ["otool", "-l", str(path)], capture_output=True, text=True, check=True
    ).stdout
    rpaths = []
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if "cmd LC_RPATH" in line:
            for j in range(i, min(i + 4, len(lines))):
                m = re.search(r"path (\S+) \(offset", lines[j])
                if m:
                    rpaths.append(m.group(1))
                    break
    return rpaths


def _relocate(dist_dir: Path) -> None:
    """Rewrite install names to @rpath, fix ids/rpaths, ad-hoc re-sign.

    A file is touched (and re-signed) when it has anything to fix: absolute
    non-system deps to rewrite, a bundled-dylib id to set, or a dead
    /nix/store LC_RPATH to drop. Files that already reference @rpath with a
    relative @loader_path rpath (how nixpkgs builds python C-extensions and
    libparse_fasm on darwin) and have no /nix/store rpath are left untouched.
    """
    lib_dir = dist_dir / "lib"
    changed = []

    for f in _iter_macho(dist_dir):
        base = f.name
        deps = _otool_deps(f)
        rpaths = _existing_rpaths(f)
        nix_rpaths = [r for r in rpaths if r.startswith("/nix/store")]
        is_bundled_dylib = (f.parent == lib_dir and base.endswith(".dylib"))

        if not deps and not nix_rpaths and not is_bundled_dylib:
            continue  # already self-contained -> ship as-is

        _make_writable(f)

        # 1. Rewrite each absolute non-system dependency to @rpath/<basename>.
        #    (-change edits an existing, longer string in place -> always fits.)
        for dep in deps:
            subprocess.run(
                ["install_name_tool", "-change", dep, f"@rpath/{Path(dep).name}", str(f)],
                check=True, capture_output=True, text=True,
            )

        # 2. A dylib living in dist/lib advertises itself as @rpath/<name>.
        if is_bundled_dylib:
            subprocess.run(
                ["install_name_tool", "-id", f"@rpath/{base}", str(f)],
                check=True, capture_output=True, text=True,
            )

        # 3. Ensure an LC_RPATH pointing at dist/lib for this file's depth, so
        #    the @rpath deps resolve to the bundled libs. Adding a load command
        #    needs header padding; if missing this is non-fatal (the nix-built
        #    tools/dylibs that need it have room -- validated by the spike).
        want = _rpath_to_lib(f, lib_dir)
        if want not in rpaths:
            r = subprocess.run(
                ["install_name_tool", "-add_rpath", want, str(f)],
                capture_output=True, text=True,
            )
            if r.returncode != 0 and "would duplicate" not in (r.stderr + r.stdout):
                print(f"⚠️  rpath no añadido a {base}: {r.stderr.strip()[:100]}")

        # 4. Drop dead /nix/store LC_RPATH entries (the bundled @loader_path
        #    rpath replaces them). -delete_rpath only shrinks the header.
        for r in nix_rpaths:
            subprocess.run(["install_name_tool", "-delete_rpath", r, str(f)],
                           capture_output=True, text=True)

        changed.append(f)

    # 4. Ad-hoc re-sign every modified Mach-O (mandatory on arm64 after edits).
    for f in changed:
        subprocess.run(["codesign", "--remove-signature", str(f)],
                       capture_output=True, text=True)
        subprocess.run(["codesign", "--force", "-s", "-", str(f)],
                       check=True, capture_output=True, text=True)


def relocate_dist(dist_dir: Path) -> None:
    """Make every Mach-O file under *dist_dir* self-contained.

    Call once, after all binaries/libraries/python files are in place.
    """
    # Files AND directories copied from the nix store are read-only.
    # install_name_tool writes a temp file next to each target and renames it,
    # so every containing directory must be writable too.
    subprocess.run(["chmod", "-R", "u+w", str(dist_dir)], check=True)

    print("➡️  macOS: recolectando cierre de dylibs...")
    _collect_and_copy_libs(dist_dir)
    print("➡️  macOS: relocalizando install names (@rpath) y firmando...")
    _relocate(dist_dir)

    # Sanity check: nothing must still point into /nix/store, neither via a
    # dependency (LC_LOAD_DYLIB) nor via a search path (LC_RPATH).
    residual = []
    for f in _iter_macho(dist_dir):
        for dep in _otool_deps(f):
            if dep.startswith("/nix/store"):
                residual.append((f, f"dep {dep}"))
        for rp in _existing_rpaths(f):
            if rp.startswith("/nix/store"):
                residual.append((f, f"rpath {rp}"))
    if residual:
        print(f"⚠️  Quedan {len(residual)} referencias a /nix/store (relocalización incompleta):")
        for f, ref in residual[:10]:
            print(f"    {f.name} -> {ref}")
    else:
        print("✅ Cierre completamente relocalizado (sin referencias a /nix/store).")
