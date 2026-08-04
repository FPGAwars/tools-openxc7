"""Chipdb generation.

One dist/chipdb/<part>.bin is generated per part of the manifest
chipdb-parts.json (single source of parts, shared with
nix/windows/default.nix), guarded by the identity stamp so that bins from
another toolchain are never reused.
"""

import hashlib
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ansi

from .families import CHIPDB_PARTS_FILE, chipdb_parts

# -- Identity stamp of the .bin files (see chipdb_identity). No leading dot
# -- on purpose: a hidden file gets lost in transit (actions/upload-artifact
# -- excludes hidden files by default since v4.4), and it also documents
# -- inside the package which toolchain the chipdb was generated with.
CHIPDB_STAMP = "chipdb-id.txt"


def chipdb_identity() -> str:
    """Identity of the .bin files: which toolchain they are valid for.

    The constids are baked into the .bin when it is generated, so a .bin
    from another nextpnr blows up AT RUNTIME with "internal IDs
    inconsistent with the supplied chip database". Reusing foreign bins
    has already let incompatible binaries slip in three times (2026-07-16,
    07-31 and 08-03), always by trusting that someone would remember to
    delete dist/.

    The identity is the hash of what determines the content: the nextpnr
    pin, the chipdb derivation, the patches that touch bbaexport and the
    parts manifest. It is the SAME definition as the CI cache key
    (.github/workflows/linux-package.yml), so that both match.
    """
    sources = [
        Path.cwd() / "nix/nextpnr-xilinx.nix",
        Path.cwd() / "nix/nextpnr-xilinx-chipdb.nix",
        Path.cwd() / CHIPDB_PARTS_FILE,
    ]
    sources += sorted((Path.cwd() / "nix/patches").glob("*.patch"))
    digest = hashlib.sha256()
    for source in sources:
        if not source.exists():
            raise SystemExit(f"❌ falta {source} para calcular la identidad del chipdb")
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()[:16]


def read_stamp(directory: Path) -> str:
    stamp_file = directory / CHIPDB_STAMP
    return stamp_file.read_text(encoding="utf-8").strip() \
        if stamp_file.exists() else ""


def write_stamp(directory: Path, identity: str):
    (directory / CHIPDB_STAMP).write_text(identity + "\n", encoding="utf-8")


def first_speedgrade(family: str, part: str) -> str:
    """First <part>-<sg> device available in the packaged prjxray-db.

    The chipdb .bin does not depend on the speedgrade (same criterion as
    nix/nextpnr-xilinx-chipdb.nix: first sorted directory).
    """
    db_dir = Path.cwd() / f"dist/share/nextpnr/external/prjxray-db/{family}"
    devices = sorted(d.name for d in db_dir.glob(f"{part}-*") if d.is_dir())
    if not devices:
        raise SystemExit(
            f"❌ No existe ningun {part}-<speedgrade> en {db_dir}")
    return devices[0]


def seed_chipdb(identity: str):
    """Copy precompiled .bin files from $OPENXC7_CHIPDB_SEED (optional).

    The chipdb .bin is identical across platforms, so a directory with
    bins already generated on another machine (e.g. the Linux build
    server) avoids regenerating them here (useful on macOS and in CI).

    The seed MUST carry the right identity stamp: pointing at a seed is
    an explicit decision, so a foreign seed is rejected instead of being
    silently ignored (which would lose an hour of regeneration) or used
    (which would package incompatible bins).
    """
    seed = os.environ.get("OPENXC7_CHIPDB_SEED")
    if not seed:
        return
    seed_dir = Path(seed)
    stamp = read_stamp(seed_dir)
    if stamp != identity:
        raise SystemExit(
            f"❌ El seed {seed_dir} no corresponde a esta toolchain:\n"
            f"   esperado: {identity}\n"
            f"   encontrado: {stamp or '(sin sello ' + CHIPDB_STAMP + ')'}\n"
            "   Sus .bin llevan otros constids y el nextpnr empaquetado los\n"
            "   rechazaria en ejecucion. Usa un seed generado con estos pines\n"
            "   o quita OPENXC7_CHIPDB_SEED para regenerarlos."
        )
    for _, part in chipdb_parts():
        src = seed_dir / f"{part}.bin"
        dst = Path.cwd() / f"dist/chipdb/{part}.bin"
        if src.exists() and not dst.exists():
            print(f"🌱 Sembrando {part}.bin desde {seed_dir}")
            shutil.copy2(src, dst)


def build_chipdb_part(family: str, part: str) -> str:
    """Generate (or reuse) dist/chipdb/<part>.bin. Returns the log.

    Both steps write to a .tmp and rename on completion: an interrupted
    process (OOM, Ctrl-C, full disk) never leaves a truncated .bba/.bin
    that a rerun could take as good and package.
    """
    log = []
    bin_file = Path.cwd() / f"dist/chipdb/{part}.bin"
    bba_file = Path.cwd() / f"dist/chipdb/{part}.bba"

    # ------ Command 1: bbaexport (part -> .bba)
    if not bin_file.exists() and not bba_file.exists():
        device = first_speedgrade(family, part)
        bbaexport_cmd = Path.cwd() / "dist/share/nextpnr/python/bbaexport.py"
        tmp_bba = bba_file.with_suffix(".bba.tmp")
        tmp_bba.unlink(missing_ok=True)
        cmd = ["pypy3", str(bbaexport_cmd),
               "--device", device, "--bba", str(tmp_bba)]
        log.append(f"➡️  Generando {bba_file.name} (device {device})")
        log.append(f"  ⚙️  {' '.join(cmd)}")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            tmp_bba.unlink(missing_ok=True)
            print(f"❌ bbaexport {part}:\n{exc.stderr}")
            raise
        os.replace(tmp_bba, bba_file)
        log.append(f"🔵 ✅{bba_file.name}")

    # ------ Command 2: bbasm (.bba -> .bin)
    if not bin_file.exists():
        tmp_bin = bin_file.with_suffix(".bin.tmp")
        tmp_bin.unlink(missing_ok=True)
        cmd = ["bbasm", "-l", str(bba_file), str(tmp_bin)]
        log.append(f"➡️  Generando {bin_file.name}")
        log.append(f"  ⚙️  {' '.join(cmd)}")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            tmp_bin.unlink(missing_ok=True)
            print(f"❌ bbasm {part}:\n{exc.stderr}")
            raise
        os.replace(tmp_bin, bin_file)
        log.append(f"🔵 ✅{bin_file.name}")
    else:
        log.append(f"🔵 📌{bin_file.name}")

    # --- Delete the temporary .bba file
    bba_file.unlink(missing_ok=True)
    return "\n".join(log)


def build_chipdb():
    print()
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  GENERACION DE LA BASE DE DATOS")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print()

    # -- The .bin files surviving from a previous run are only valid if
    # -- they come from THIS toolchain: otherwise they are discarded and
    # -- regenerated. They used to be reused blindly and the package
    # -- shipped with an incompatible chipdb that was only detected at
    # -- runtime (three times: 2026-07-16, 07-31 and 08-03).
    identity = chipdb_identity()
    chipdb_dir = Path.cwd() / "dist/chipdb"
    chipdb_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(chipdb_dir.glob("*.bin"))
    if existing:
        stamp = read_stamp(chipdb_dir)
        if stamp == identity:
            print(f"📌 Reutilizando {len(existing)} .bin ya presentes "
                  f"(identidad {identity})")
        else:
            print(f"♻️  Descartando {len(existing)} .bin de otra toolchain "
                  f"(sello {stamp or 'ausente'} ≠ {identity}); se regeneran")
            for old_bin in existing:
                old_bin.unlink()
            for leftover in chipdb_dir.glob("*.bba"):
                leftover.unlink()

    # -- Reuse precompiled bins if a seed was given
    seed_chipdb(identity)

    # -- Generate every part of the manifest. bbaexport is independent per
    # -- part -> parallelizable with $OPENXC7_CHIPDB_JOBS (default 1; each
    # -- job consumes several GB of RAM with the big parts).
    try:
        jobs = int(os.environ.get("OPENXC7_CHIPDB_JOBS") or "1")
    except ValueError:
        print("⚠️  OPENXC7_CHIPDB_JOBS no numerico; usando 1")
        jobs = 1
    parts = chipdb_parts()
    with ThreadPoolExecutor(max_workers=max(jobs, 1)) as pool:
        for result in pool.map(lambda fp: build_chipdb_part(*fp), parts):
            print(result)

    # -- Stamp: from here on these .bin can be reused or serve as a seed,
    # -- and any pin/patch change will invalidate the stamp on its own.
    write_stamp(chipdb_dir, identity)
    print(f"🔏 chipdb sellado: {identity}")

    # -- Size summary
    print()
    for _, part in parts:
        bin_file = Path.cwd() / f"dist/chipdb/{part}.bin"
        mb = bin_file.stat().st_size / (1024 * 1024)
        print(f"📦 {part}.bin: {mb:.0f} MB")
    print()
