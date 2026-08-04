"""openXC7 packer, split into modules.

``openxc7-pack.py`` (repo root) is the thin CLI shim that runs the flow.
The implementation lives here:

* ``pack.platform``   -- current-platform detection (``plat_token``, ``IS_DARWIN``)
* ``pack.families``   -- part-name -> family rule and the parts manifest
* ``pack.relocate``   -- executables, dynamic libraries and python deps
* ``pack.components`` -- per-tool phases (copy, wrappers, tool data)
* ``pack.chipdb``     -- chipdb generation, identity stamp and seeding
* ``pack.assemble``   -- dist/ tree init, env/VERSION files and the tarball

``macpack.py`` (repo root) is the Darwin Mach-O relocation backend used by
``pack.relocate``.
"""

# ------ Relative names of the distribution directories
# -- Base of the distribution
DIST = "dist"
BIN = "bin"
LIBEXEC = "libexec"
LIB = "lib"

# -- FILE TYPES
EXECUTABLE = 0
SHELL_SCRIPT = 1
PYTHON = 2
