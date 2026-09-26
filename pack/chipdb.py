"""Chipdb generation, and the placeholder a tools-only pack leaves behind.

One dist/chipdb/chipdb-<die>.bin is generated per die of the manifest
chipdb-parts.json (single source of parts, shared with
nix/windows/default.nix): every part of a die routes on that die's chipdb,
so xc7a35t and xc7a50t parts share one file. The set is guarded by the
identity stamp so that bins from another toolchain are never reused.

A release package carries those bins in chipdb/, next to chipdb-id.txt.
``--no-chipdb`` is a local tools-only pack: chipdb/ gets the README this
module writes and no bins, and that tree is not a release package. Run
as a script to write that placeholder into a directory:

    python3 -m pack.chipdb <package>/chipdb
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import ansi

from .families import CHIPDB_PARTS_FILE, chipdb_dies, chipdb_parts, die_of

# -- Identity stamp of the .bin files (see chipdb_identity). No leading dot
# -- on purpose: a hidden file gets lost in transit (actions/upload-artifact
# -- excludes hidden files by default since v4.4), and it also documents
# -- inside the package which toolchain the chipdb was generated with.
CHIPDB_STAMP = "chipdb-id.txt"

# -- The placeholder that occupies chipdb/ in a local --no-chipdb pack. It
# -- is the first thing a user looking for a missing .bin will read, so it
# -- says this tree is not a release package and where the files belong.
PLACEHOLDER = "README.txt"
PLACEHOLDER_TEXT = """\
This directory is empty because this tree was packed with --no-chipdb.

That is a local tools-only pack, not a release package. A release package
carries the device databases here: one file per die, chipdb-<die>.bin,
named by XILINX-PARTS-INDEX.json at the root of the package (the chipdb
field of each part this release built). Apio does not download them.
Parts the packaged database supports that this release did not build are
listed there with generated=false: supported, not built.

chipdb-id.txt, next to those files, is the identity stamp of the set. A
chipdb file is only valid with the package of the SAME release tag: it
is generated for the exact nextpnr that package carries, and nextpnr
cannot always tell a foreign one apart.
"""

# -- Peak resident memory of the chipdb generator, per die, in MiB: the
# -- build server, one die at a time (bbasm stays far below). Parallel
# -- generation adds these up, and the two biggest dies alone would take
# -- 22 GB, more than a hosted CI runner has. A die missing from the table
# -- counts as the biggest one.
DIE_PEAK_MIB = {
    "xc7s25": 1007,
    "xc7z010": 1097,
    "xc7s50": 1745,
    "xc7a50t": 1759,
    "xc7z020": 2608,
    "xc7a100t": 3002,
    "xc7z030": 3833,
    "xc7a200t": 6234,
    "xc7z045": 9429,
    "xc7z100": 12443,
}

# -- Default memory budget of a parallel generation: what a 16 GB runner
# -- can give it. Under it, xc7z045 and xc7z100 never run at the same time.
DEFAULT_MEM_GB = 14


def chipdb_file(die: str) -> str:
    """Name of the chipdb file of a die."""
    return f"chipdb-{die}.bin"


def write_placeholder(directory: Path) -> Path:
    """Create <directory>/README.txt, the tools-only chipdb placeholder."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / PLACEHOLDER
    target.write_text(PLACEHOLDER_TEXT, encoding="utf-8")
    return target


def skip_chipdb():
    """Leave dist/chipdb as the tools-only placeholder instead of bins.

    Nothing is deleted: the .bin are the expensive part of a build and
    dist/chipdb deliberately survives across runs (see
    pack.assemble.distribution_init), so leftovers from a full pack are
    reported and the run stops rather than shipping half a package or
    throwing away the generation.
    """
    chipdb_dir = Path.cwd() / "dist/chipdb"
    chipdb_dir.mkdir(parents=True, exist_ok=True)
    leftovers = sorted(chipdb_dir.glob("*.bin"))
    if leftovers:
        raise SystemExit(
            f"❌ --no-chipdb: dist/chipdb still holds {len(leftovers)} .bin "
            "from a previous run.\n"
            "   A tools-only pack ships only the placeholder "
            f"{PLACEHOLDER}, and these\n"
            "   are too expensive to delete here. Move them out and re-run:\n"
            "       mkdir -p chipdb-bins\n"
            f"       mv dist/chipdb/*.bin dist/chipdb/{CHIPDB_STAMP} chipdb-bins/\n"
            "   (that directory is what OPENXC7_CHIPDB_SEED and\n"
            "   validate-package.sh --chipdb-dir take.)"
        )
    # The stamp belongs to a set of bins, and an interrupted generation may
    # have left a .bba behind: neither has any business in the package.
    (chipdb_dir / CHIPDB_STAMP).unlink(missing_ok=True)
    for stale in chipdb_dir.glob("*.bba*"):
        stale.unlink()
    target = write_placeholder(chipdb_dir)
    print()
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  CHIPDB AUSENTE (pack local, sin bins)")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print(f"🔵 ✅chipdb/{target.name} (no es un paquete de release)")
    print()


def chipdb_identity() -> str:
    """Identity of the .bin files: which toolchain they are valid for.

    A chipdb carries the ids of the nextpnr source it was generated from
    (its constids.inc) and the content of one revision of prjxray-db, and
    nextpnr cannot tell a foreign one apart in every case. Reusing foreign
    bins has already let incompatible binaries slip in three times
    (2026-07-16, 07-31 and 08-03), always by trusting that someone would
    remember to delete dist/.

    The identity is the hash of what determines the content: the nextpnr
    revision (generator, constids, metadata and bbasm all come from its
    source tree), the prjxray-db revision, the chipdb derivation, the
    patches and the parts manifest (which dies are generated). The CI
    cache key covers the same set (.github/workflows/chipdb.yml), so that
    both match.
    """
    sources = [
        Path.cwd() / "nix/nextpnr-xilinx.nix",
        Path.cwd() / "nix/prjxray-db.nix",
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


def database_dies(db_root: Path) -> dict:
    """{base part: die} as the packaged prjxray-db maps them.

    <family>/mapping/parts.yaml names the device of every part and
    <family>/mapping/devices.yaml the fabric of every device: that fabric
    is the die whose chipdb the part needs.
    """
    import yaml  # the packaging shell has it; the rest of pack/ does not need it

    result = {}
    for family_dir in sorted(path for path in Path(db_root).iterdir()
                             if (path / "mapping").is_dir()):
        mapping = family_dir / "mapping"
        parts = yaml.safe_load((mapping / "parts.yaml").read_text()) or {}
        devices = yaml.safe_load((mapping / "devices.yaml").read_text()) or {}
        for part, info in parts.items():
            base_part = part.rsplit("-", 1)[0]
            fabric = (devices.get(info["device"]) or {}).get("fabric")
            result[base_part] = fabric or info["device"]
    return result


def check_dies(db_root: Path) -> None:
    """Refuse a manifest part whose die_of() disagrees with the database.

    The generator is asked for a die by name; a wrong die_of() would build
    a chipdb that lacks the part's package, and the index would promise it
    to apio anyway.
    """
    mapped = database_dies(db_root)
    wrong = []
    for _, part in chipdb_parts():
        if mapped.get(part) != die_of(part):
            wrong.append(f"{part}: die_of says {die_of(part)}, "
                         f"the database {mapped.get(part) or 'nothing'}")
    if wrong:
        raise SystemExit("❌ die_of() y la base de datos no coinciden:\n   "
                         + "\n   ".join(wrong))


def seed_chipdb(identity: str):
    """Copy precompiled .bin files from $OPENXC7_CHIPDB_SEED (optional).

    The chipdb .bin is identical across platforms, so a directory with
    bins already generated on another machine (e.g. the Linux build
    server) avoids regenerating them here (useful on macOS and in CI).

    The seed MUST carry the right identity stamp: pointing at a seed is
    an explicit decision, so a foreign seed is rejected instead of being
    silently ignored (which would lose the regeneration time) or used
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
            "   Sus .bin salen de otra revision de nextpnr o de prjxray-db, y\n"
            "   el nextpnr empaquetado no siempre sabria rechazarlos. Usa un\n"
            "   seed generado con estas revisiones o quita OPENXC7_CHIPDB_SEED\n"
            "   para regenerarlos."
        )
    for _, die in chipdb_dies():
        src = seed_dir / chipdb_file(die)
        dst = Path.cwd() / "dist/chipdb" / chipdb_file(die)
        if src.exists() and not dst.exists():
            print(f"🌱 Sembrando {chipdb_file(die)} desde {seed_dir}")
            shutil.copy2(src, dst)


def _run_measured(cmd: list) -> tuple:
    """Run *cmd*; return (exit code, output, seconds, peak RSS in MiB).

    The peak is the child's own, from wait4() -- the same rusage GNU time
    reports -- so it stays per die when several dies run at once. The
    output goes through a temporary file, not a pipe, so waiting for the
    child cannot deadlock on a full pipe.
    """
    started = time.monotonic()
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(cmd, stdout=output, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)
        _, status, usage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
        output.seek(0)
        text = output.read().decode(errors="replace")
    # ru_maxrss is KiB on Linux and bytes on macOS
    peak = usage.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    return proc.returncode, text, time.monotonic() - started, peak


def build_chipdb_die(family: str, die: str) -> str:
    """Generate (or reuse) dist/chipdb/chipdb-<die>.bin. Returns the log.

    The generator of the packaged nextpnr's own source tree writes the
    .bba from the packaged prjxray-db, and bbasm assembles it. Both steps
    write to a .tmp and rename on completion: an interrupted process (OOM,
    Ctrl-C, full disk) never leaves a truncated .bba/.bin that a rerun
    could take as good and package.
    """
    chipdb_dir = Path.cwd() / "dist/chipdb"
    bin_file = chipdb_dir / chipdb_file(die)
    if bin_file.exists():
        return f"🔵 📌{bin_file.name}"

    generator = os.environ.get("NEXTPNR_XILINX_CHIPDB_GEN")
    if not generator or not Path(generator).is_file():
        raise SystemExit(
            "❌ NEXTPNR_XILINX_CHIPDB_GEN no apunta al generador del chipdb "
            f"({generator or 'sin definir'}): ejecuta el packer dentro de "
            "`nix develop .#pack`")
    database = Path.cwd() / f"dist/share/nextpnr/external/prjxray-db/{family}"
    bba_file = chipdb_dir / f"chipdb-{die}.bba"
    tmp_bba = bba_file.with_suffix(".bba.tmp")
    tmp_bin = bin_file.with_suffix(".bin.tmp")
    log = []

    # ------ Command 1: the generator (prjxray-db die -> .bba)
    tmp_bba.unlink(missing_ok=True)
    cmd = [sys.executable, generator, "--xray", str(database),
           "--device", die, "--bba", str(tmp_bba)]
    log.append(f"➡️  Generando {bba_file.name}")
    log.append(f"  ⚙️  {' '.join(cmd)}")
    code, output, seconds, peak = _run_measured(cmd)
    if code != 0:
        tmp_bba.unlink(missing_ok=True)
        raise SystemExit(f"❌ generador del chipdb {die} (exit {code}):\n{output}")
    os.replace(tmp_bba, bba_file)
    log.append(f"🔵 ✅{bba_file.name} ({seconds:.1f} s, pico {peak:.0f} MiB)")

    # ------ Command 2: bbasm (.bba -> .bin)
    tmp_bin.unlink(missing_ok=True)
    cmd = ["bbasm", "--le", str(bba_file), str(tmp_bin)]
    log.append(f"  ⚙️  {' '.join(cmd)}")
    code, output, seconds, peak = _run_measured(cmd)
    if code != 0:
        tmp_bin.unlink(missing_ok=True)
        raise SystemExit(f"❌ bbasm {die} (exit {code}):\n{output}")
    os.replace(tmp_bin, bin_file)
    log.append(f"🔵 ✅{bin_file.name} ({seconds:.1f} s, pico {peak:.0f} MiB)")

    # --- Delete the intermediate .bba file
    bba_file.unlink(missing_ok=True)
    return "\n".join(log)


def generate_dies(dies: list, jobs: int, budget_mib: float, build=None) -> None:
    """Build every (family, die), at most *jobs* at once, within the budget.

    A die starts only when its peak (DIE_PEAK_MIB) fits in what the running
    ones leave of *budget_mib*; the biggest pending die that fits goes
    first, and a die bigger than the whole budget runs alone. With the
    default budget the two biggest dies never overlap.
    """
    build = build or build_chipdb_die
    pending = sorted(dies, key=lambda entry: -peak_of(entry[1]))
    running = {}
    finished = []
    errors = []
    done = threading.Condition()

    def worker(entry):
        try:
            result = build(*entry)
        except BaseException as error:  # SystemExit included: report it
            result = error
        with done:
            finished.append((entry, result))
            done.notify()

    while pending or running:
        while len(running) < max(jobs, 1) and pending and not errors:
            free = budget_mib - sum(peak_of(die) for _, die in running)
            fitting = [entry for entry in pending if peak_of(entry[1]) <= free]
            if not fitting and not running:
                fitting = pending[:1]     # bigger than the budget: alone
            if not fitting:
                break
            entry = fitting[0]
            pending.remove(entry)
            thread = threading.Thread(target=worker, args=(entry,))
            running[entry] = thread
            print(f"⏳ {chipdb_file(entry[1])}: arranca "
                  f"({time.strftime('%H:%M:%S')})", flush=True)
            thread.start()
        if errors and not running:
            break
        with done:
            while not finished:
                done.wait()
            entry, result = finished.pop(0)
        running.pop(entry).join()
        if isinstance(result, BaseException):
            errors.append(result)
            print(f"❌ {chipdb_file(entry[1])} ({time.strftime('%H:%M:%S')})",
                  flush=True)
        else:
            print(result, flush=True)
            print(f"⌛ {chipdb_file(entry[1])}: termina "
                  f"({time.strftime('%H:%M:%S')})", flush=True)
    if errors:
        raise errors[0]


def peak_of(die: str) -> int:
    return DIE_PEAK_MIB.get(die, max(DIE_PEAK_MIB.values()))


def _env_number(name: str, default, kind=int):
    try:
        return kind(os.environ.get(name) or default)
    except ValueError:
        print(f"⚠️  {name} no numerico; usando {default}")
        return default


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
    # dist/chipdb survives across runs (the .bin are expensive), so a
    # previous --no-chipdb pack may have left its placeholder behind: a
    # package that ships the bins must not also tell the user to download
    # them.
    (chipdb_dir / PLACEHOLDER).unlink(missing_ok=True)
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
    for leftover in chipdb_dir.glob("*.bba*"):
        leftover.unlink()

    # -- Each part of the manifest must route on the die the chipdb is
    # -- generated for: the database decides, die_of() must agree.
    check_dies(Path.cwd() / "dist/share/nextpnr/external/prjxray-db")

    # -- Reuse precompiled bins if a seed was given
    seed_chipdb(identity)

    # -- One chipdb per die. The dies are independent -> parallelizable
    # -- with $OPENXC7_CHIPDB_JOBS (default 1), within a memory budget of
    # -- $OPENXC7_CHIPDB_MEM_GB (default 14): each generation takes
    # -- between 1 and 12.4 GB.
    jobs = _env_number("OPENXC7_CHIPDB_JOBS", 1)
    budget = _env_number("OPENXC7_CHIPDB_MEM_GB", DEFAULT_MEM_GB, float)
    dies = chipdb_dies()
    print(f"🧮 {len(dies)} dies de {len(chipdb_parts())} parts; "
          f"{jobs} a la vez, presupuesto {budget:g} GB")
    started = time.monotonic()
    generate_dies(dies, jobs, budget * 1024)
    print(f"⏱️  chipdb: {time.monotonic() - started:.0f} s")

    missing = [chipdb_file(die) for _, die in dies
               if not (chipdb_dir / chipdb_file(die)).is_file()]
    if missing:
        raise SystemExit(f"❌ faltan chipdb: {', '.join(missing)}")

    # -- Stamp: from here on these .bin can be reused or serve as a seed,
    # -- and any revision/patch change will invalidate the stamp on its own.
    write_stamp(chipdb_dir, identity)
    print(f"🔏 chipdb sellado: {identity}")

    # -- Size summary
    print()
    for _, die in dies:
        bin_file = chipdb_dir / chipdb_file(die)
        mb = bin_file.stat().st_size / (1024 * 1024)
        print(f"📦 {bin_file.name}: {mb:.0f} MB")
    print()


def main() -> None:
    """Write the tools-only placeholder into the directory given as argv[1]."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 -m pack.chipdb <chipdb-dir>")
    target = write_placeholder(Path(sys.argv[1]))
    print(f"chipdb placeholder written: {target}")


if __name__ == "__main__":
    main()
