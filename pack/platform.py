"""Current-platform detection for the packer."""

import platform


# -- Current platform. Packaging for macOS (Mach-O binaries) is different
# -- from the Linux one (ELF) and lives in the `macpack` module, which is
# -- only imported on Darwin (see pack.relocate). The Linux path stays
# -- untouched.
IS_DARWIN = platform.system() == "Darwin"


def plat_token() -> str:
    """<os>-<arch> token for the package name.

    On Linux x86_64 it returns 'linux-x86-64' (identical to the historic
    names -> a no-op for Linux users). On macOS Apple Silicon,
    'darwin-arm64'. Aligned with the FPGAwars/tools-oss-cad-suite tokens.
    """
    sysname = platform.system()
    machine = platform.machine()
    if sysname == "Linux":
        arch = "x86-64" if machine in ("x86_64", "amd64") else \
               ("aarch64" if machine in ("aarch64", "arm64") else machine)
        return f"linux-{arch}"
    if sysname == "Darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else \
               ("x86-64" if machine == "x86_64" else machine)
        return f"darwin-{arch}"
    raise SystemExit(f"❌ Plataforma no soportada: {sysname} {machine}")
