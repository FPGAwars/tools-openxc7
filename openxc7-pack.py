#!/usr/bin/env python3

# -- Thin CLI shim over the `pack` package. Same invocation as always
# -- (`python openxc7-pack.py` from the repo root, inside the packaging
# -- devShell) and same environment variables: OPENXC7_PACK_DATE,
# -- OPENXC7_CHIPDB_SEED, OPENXC7_PARTS_INDEX and OPENXC7_CHIPDB_JOBS
# -- (PRJXRAY_NO_FILE_LOCK is honored by the util.py locking patch that
# -- ships inside the package).
# -- The implementation lives in pack/ (platform, families, relocate,
# -- components, chipdb, assemble); macpack.py is the Darwin backend.

import os
import sys
from pathlib import Path

import ansi

from pack import DIST
from pack.assemble import (
    build_tarball,
    distribution_init,
    write_env,
    write_version,
)
from pack.chipdb import build_chipdb, skip_chipdb
from pack.components import install_components
from pack.platform import IS_DARWIN

if IS_DARWIN:
    # -- The macOS (Mach-O) packaging backend, only importable on Darwin
    from pack.relocate import macpack

# -- `--chipdb-only`: stop after the chipdb is generated (or seeded) and
# -- stamped, leaving dist/chipdb/*.bin + chipdb-id.txt in place. This is
# -- what the CI `chipdb` job runs: the .bin files are platform-independent
# -- and generated once, then every platform package seeds from them.
CHIPDB_ONLY = "--chipdb-only" in sys.argv[1:]

# -- `--no-chipdb` (or OPENXC7_NO_CHIPDB=1): pack WITHOUT the device
# -- databases. chipdb/ ships a README.txt and apio downloads the .bin its
# -- board needs from the release assets, guided by PARTS-INDEX.json. This
# -- is what the release packages are; the full variant stays for local
# -- work and for anyone wanting a self-contained tree.
NO_CHIPDB = ("--no-chipdb" in sys.argv[1:]
             or os.environ.get("OPENXC7_NO_CHIPDB") == "1")
if NO_CHIPDB and CHIPDB_ONLY:
    sys.exit("❌ --chipdb-only y --no-chipdb se excluyen")

# -----------------
#    MAIN
# -----------------
print(ansi.CLS, end='', flush=True)
print(f"{ansi.BLUE}", end='', flush=True)
print("─────────────────────────")
print("OPENXC7-PACK")
print("─────────────────────────")
print(ansi.DEFAULT, end='', flush=True)
print("Pack the toolchains binaries for Xilinx FPGAs...")


# -- Initialize the distribution
distribution_init()

# -- Get the required binaries, libraries and data
install_components()

# -- On macOS: collect the dylib closure into dist/lib, relocate the
# -- install names to @rpath/@loader_path and then sign (ad-hoc) -- in
# -- that order: signing must come after the relocation. On Linux nothing
# -- is done: the wrappers use the dynamic loader with --library-path.
if IS_DARWIN:
    macpack.relocate_dist(Path.cwd() / DIST)

# --- Generation of the database
# --- One <part>.bin per part of chipdb-parts.json, or the placeholder
# --- that says where apio downloads them from
if NO_CHIPDB:
    skip_chipdb()
else:
    build_chipdb()

if CHIPDB_ONLY:
    print(f"{ansi.GREEN}chipdb-only: dist/chipdb generated and stamped; stopping here.{ansi.DEFAULT}")
    sys.exit(0)

# -- Final configuration
write_env()

# -- Generate the version
date = write_version()

# -- Generate the tarball
build_tarball(date)
