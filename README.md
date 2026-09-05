# tools-openxc7

> **Note:** Please **do not** open issues in this repository.
> For any questions, discussions, or bug reports, use the [main Apio repository](https://github.com/FPGAwars/apio).

This Apio package contains the Xiling architecture support of Apio. It is based on selected binaries from the [openXC7 project](https://github.com/openxc7):
an open source toolchain for **Xilinx 7-series FPGAs** (Artix-7 and friends) and is not intended for standalone
operation but as part of [Apio](https://github.com/FPGAwars/apio).

This repository does not develop the toolchain itself — it **builds and packages**
using [Nix](https://nixos.org), and publish one Apio package tarball per Apio supported platform,

## What is inside a package

| Component                                 | Upstream                                             | Role in the flow                                   |
| ----------------------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| `nextpnr-xilinx`                          | [openXC7](https://github.com/openXC7/nextpnr-xilinx) | Place & route, and FASM output                     |
| `xc7frames2bit`, `bitread`, `xc7patch`    | [Project X-Ray](https://github.com/f4pga/prjxray)    | Frames → bitstream, and bitstream inspection       |
| `fasm2frames` + the `fasm` Python library | [openXC7 fasm](https://github.com/openxc7/fasm)      | FASM → configuration frames                        |
| `chipdb/`                                 | built here, downloaded on demand                     | Where apio leaves the per-FPGA device database nextpnr needs |
| `XILINX-PARTS-INDEX.json`                 | built here                                           | Which chipdb file each part needs, which of them this release built, and the asset, sizes and hashes of each one |
| `share/nextpnr/external/prjxray-db`       | Project X-Ray database                               | Pin/part data (`part.yaml`, `package_pins.csv`, …) |

Synthesis is **not** part of this package: it comes from `yosys`, shipped by
[oss-cad-suite](https://github.com/FPGAwars/tools-oss-cad-suite).

## Supported Boards and FPGAs

For latest information see [Apio supported boards](https://fpgawars.github.io/apio/docs/supported-boards/) and
[Apio supported FPGAs](https://fpgawars.github.io/apio/docs/supported-fpgas/). FPGAs that are supported by
Openxc7 but not by Apio can easily be added in the [Apio Definition Package repo](https://github.com/fpgawars/apio-definitions).

Every package ships the prjxray database of three 7-series families, and the
release publishes one chipdb asset per FPGA below — apio downloads the one
your board needs into the package's `chipdb/` directory the first time you
build (the package itself is ~200 MB instead of ~650 MB):

| Family         | Device   | Footprints                             | Boards (examples)                            |
| -------------- | -------- | -------------------------------------- | -------------------------------------------- |
| Artix-7        | xc7a35t  | `cpg236`, `csg324`, `fgg484`, `ftg256` | Basys3, Arty A7-35, Cmod A7                  |
| Artix-7        | xc7a50t  | `csg324`, `fgg484`                     |                                              |
| Artix-7        | xc7a100t | `csg324`, `ftg256`, `fgg484`, `fgg676` | Arty A7-100, Nexys                           |
| Artix-7        | xc7a200t | `fbg484`                               |                                              |
| Spartan-7      | xc7s50   | `csga324`                              | Arty S7-50                                   |
| Zynq-7000 (PL) | xc7z010  | `clg400`                               | Zybo Z7-10, EBAZ4205                         |
| Zynq-7000 (PL) | xc7z020  | `clg400`, `clg484`                     | Pynq-Z1/Z2, Arty Z7-20, Zybo Z7-20, ZedBoard |

Zynq support is **PL-only**: the toolchain produces the fabric bitstream
(loaded over JTAG); the ARM PS boots on its own. The Arty S7-25 cannot be
supported yet (`xc7s25` is not in the prjxray database), and Kintex-7 is
work in progress (its differential-input bits are missing upstream).

`chipdb-parts.json` is the **single source of truth** for that list: it is read by
the packer, by the Windows build (which database families to ship) and by the CI
assertions. Adding a board whose footprint already exists in the prjxray database
is a one-line change there.

## Building the packages from source (developers)

The build is reproducible with **Nix** (every flake input at a fixed revision). There is no
cross-compilation between Linux and macOS — each is built natively on its own
machine — while the Windows package **is** cross-compiled from Linux, because
Nix does not run on Windows.

### Linux / macOS (native)

```bash
nix develop .#pack                                   # packaging shell
python3.12 openxc7-pack.py --no-chipdb               # -> apio-openxc7-<platform>-<date>.tgz
python3.12 openxc7-pack.py                           # the same, carrying every chipdb bin
```

`--no-chipdb` (or `OPENXC7_NO_CHIPDB=1`) is what the released packages are
built with: `chipdb/` gets a `README.txt` and nothing else. Without it the
packer generates every part of the manifest into the package, which is what
you want for a self-contained local tree.

The first `nix develop` builds the whole toolchain and takes a while (tens of
minutes); later ones take seconds. `nix develop` (without `.#pack`) gives the
full development shell; `.#pack` is the lighter profile the packer actually
needs.

Generating the chipdb is the slow part (one `bbaexport` per part, RAM hungry).
The `.bin` files are **platform independent and byte-identical**, so they can be
generated once and reused:

| Variable              | Meaning                                                 |
| --------------------- | ------------------------------------------------------- |
| `OPENXC7_PACK_DATE`   | Force the package date (`YYYY-MM-DD`), instead of today |
| `OPENXC7_CHIPDB_SEED` | Directory of prebuilt `.bin` files to reuse             |
| `OPENXC7_CHIPDB_JOBS` | Parallel chipdb jobs (memory hungry — raise with care)  |
| `OPENXC7_NO_CHIPDB`   | `1` packs without the chipdb (same as `--no-chipdb`)    |
| `OPENXC7_PARTS_INDEX` | The dated document to embed as `XILINX-PARTS-INDEX.json` |

> **Caveat:** when you change the toolchain revisions, remove `dist/`
> before packing (`rm -rf dist`). Chipdb files built against a different
> revision are silently incompatible and the toolchain rejects them at runtime
> with an "internal IDs inconsistent" error.

### Windows (cross-compiled from Linux)

```bash
nix build .#packages.x86_64-linux.openxc7-windows-amd64-tools
```

The result is deliberately a **tools-only tree** without `chipdb/`. CI adds the
on-demand placeholder and the `XILINX-PARTS-INDEX.json` built by the single `chipdb.yml`
job, then creates the tarball and validates it against that job's bins — the same
ones the Linux and macOS gates use. To reproduce that assembly locally:

```bash
cp -aL result package-win && chmod -R u+w package-win
python3 -m pack.chipdb package-win/chipdb          # the placeholder README.txt
cp /path/to/XILINX-PARTS-INDEX.json package-win/XILINX-PARTS-INDEX.json
CHIPDB_SOURCE=restored-from-cache CHIPDB_ID="$(cat /path/to/chipdb-bins/chipdb-id.txt)" \
  bash scripts/build-info.sh windows-amd64 YYYY-MM-DD \
  apio-openxc7-windows-amd64-YYYYMMDD.tgz package-win/BUILD-INFO.json
tar czhf apio-openxc7-windows-amd64-YYYYMMDD.tgz --mode=u+w -C package-win .
```

The `nextpnr-xilinx.exe` in the tools tree embeds a Python interpreter, so
`--post-route` scripts (and therefore `apio report`) work like on Linux/macOS.

## Validating a package

Everything the CI gates on is a script you can run locally, which is the point:
a release is only as trustworthy as the checks you can reproduce.

```bash
scripts/validate-package.sh <package.tgz> --chipdb-dir /path/to/chipdb-bins
scripts/validate-package.sh <package.tgz> --chipdb-dir <dir> --wine
scripts/validate-package.sh <package.tgz> --chipdb-dir <dir> --parts "xc7a35tcpg236" --keep
```

`--chipdb-dir` is the directory of `.bin` the release publishes as per-FPGA
assets: the gate checks them against the package's `XILINX-PARTS-INDEX.json` and then
**injects** them into the extracted tarball, exactly where apio's loader leaves
them, so what is validated is the tree a user ends up with. A package built
with the chipdb inside needs no such directory.

It validates the package **inside its tarball** (never the freshly built tree)
and exits non-zero on any failure:

- the layout, that `chipdb/` holds only the placeholder, and that every part
  of `chipdb-parts.json` is in `XILINX-PARTS-INDEX.json` with the `chipdb-size` and
  `chipdb-sha256` of the chipdb file the release publishes for it;
- feature markers and `--version` inside the *packaged* binary, so a stale
  binary cannot sneak into a release;
- on macOS, the ad-hoc signature and that no Mach-O load command still points
  into `/nix/store`;
- an end-to-end run for **every** part: synthesis → `nextpnr-xilinx` with
  `router2` and a `--post-route` script → `fasm2frames` → `xc7frames2bit` → a
  real, non-empty bitstream.

That last step is also available on its own:

```bash
e2e/run-parts.sh <extracted-package-dir> <workdir> [wine]
```

The second layer is the **regression suite**: 23 declarative tests (one
folder + `test.json` each) that run real designs through the whole flow on
every packaged family — primitives, structural properties, a parametric
congestion pair, and the untouched upstream demo projects — and compare
fmax/utilisation/router-time against per-platform baselines:

```bash
scripts/fetch-demos.sh                              # locked third-party sources
scripts/regress.sh <package.tgz> --chipdb-dir <dir> # the whole catalogue
scripts/regress.sh <pkg> --chipdb-dir <dir> --test srl --json report.json
```

A third check keeps the installers honest about what is actually published:

```bash
scripts/check-versions.sh            # promoted release vs apio's remote-config
```

## Releases and CI

Each platform has its own reusable workflow, on its own native runner, carrying
the same gate — so the very same build and validation runs whether you ask for a
single package or for a full release:

| Workflow | What it does |
|---|---|
| `test.yaml` | Per-commit compile test: linux, macos and windows-cross jobs (push/PR guard) |
| `chipdb.yml` | Owns chipdb generation/cache, identity, the per-FPGA release assets (cached too) and `XILINX-PARTS-INDEX.json` |
| `linux-package.yml` | Consumes the chipdb artifacts, then builds + validates `linux-x86-64` |
| `darwin-package.yml` | Consumes the chipdb artifacts, then builds + validates `darwin-arm64` |
| `windows-package.yml` | Consumes the chipdb artifacts, then cross-builds + validates `windows-amd64` under wine |
| `build-pre-release.yaml` | Daily orchestrator (FPGAwars convention): prepares chipdb, builds the three platforms, then publishes |
| `make-pre-release-stable.yaml` | Manual dispatch: re-verifies a candidate and marks it stable + latest (apio's remote-config is then updated by hand) |

`build-pre-release.yaml` creates the release **only after every platform is
green**, as a dated **prerelease** (never "latest"), with the three tarballs,
one `apio-xilinx-chipdb-<base-part>-<YYYYMMDD>.bin.tgz` per chipdb file it
built, `XILINX-PARTS-INDEX.json`, and a `SHA256SUMS` covering every one of them
(written in the publishing job from the bytes it uploads, so it cannot drift
from the release).

`XILINX-PARTS-INDEX.json` is published under the same name every package carries it
at its root: which release it belongs to is written inside it (`release-tag`),
so the file name does not repeat the date. It is keyed by the full part number
(`xc7a200tfbg484-3`: device, package, speed grade) and says, for each one,
whether this release built it and — if it did — the chipdb file it needs
(`chipdb`, `chipdb-size`, `chipdb-sha256`: what must end up on disk) and the
asset that carries it (`asset`, `asset-size`, `asset-sha256`: what gets
downloaded). Which parts share a chipdb file is ours to change, so the index
names one per part: today the speed grades of a base part repeat the same
file, and a loader that keeps what is already on disk with the right
`chipdb-sha256` downloads it once. Parts the packaged prjxray database supports
but the release did not build are listed with `"generated": false`, so apio can
tell "not in this release" from "unknown part". Since no package ships a
chipdb, that index and the per-FPGA assets are the whole contract: each
platform's L1 and L2 gates run with those very bins injected into the extracted
tarball. Old prereleases are
pruned automatically; promoting a candidate to a real release is a deliberate
one-click human step, and everything after that click is automated.

Asset names must match the release tag: apio derives the package date from the
**tag** (`2026-07-31` → `20260731`), not from the file name, so a mismatch turns
into a 404 at install time.

## Repository layout

| Path | What it is |
|---|---|
| `flake.nix`, `nix/` | The reproducible build: every package, the dev shells and the Windows cross recipe |
| `openxc7-pack.py`, `pack/`, `macpack.py` | The packer: a thin CLI over the `pack/` modules (unit-tested in `tests/`); the macOS backend relocates Mach-O libraries and re-signs them |
| `chipdb-parts.json` | The part manifest (family → footprints) — one line here per new part |
| `regress/` | The declarative regression suite (tests, baselines, locked third-party demos) |
| `scripts/`, `e2e/` | Validation you can run locally, and the multi-part end-to-end |
| — | End-user install scripts live on `archive/standalone-installers` (this is an apio package) |
| `udev/` | USB rules needed to program boards on Linux (copy of openFPGALoader's) |
| `example/`, `config/` | The Basys3 LED example and board constraint files |
| `.github/workflows/` | CI: guards, per-platform packages, release |

## Credits

The openXC7 toolchain is developed by the [openXC7 project](https://github.com/openxc7)
and builds on [Project X-Ray](https://github.com/f4pga/prjxray),
[nextpnr](https://github.com/YosysHQ/nextpnr) and
[Yosys](https://github.com/YosysHQ/yosys). All credit for the tools themselves
belongs to them.

This repository was created by **Juan González-Gómez
([Obijuan](https://github.com/Obijuan))** for [FPGAwars](https://github.com/FPGAwars),
who set up the original Nix packaging, the installation scripts, the environment
and the Basys3 example that this project still builds on. 


**Carlos Venegas ([cavearr](https://github.com/cavearr))**
contributed, on top of that foundation: multi-platform support (native macOS
on Apple Silicon and Windows cross-compiled from Linux), fixes to the openXC7
toolchain itself (routing, timing and packer bugs, all merged upstream,
nextpnr-xilinx #102/#104/#105/#106 and prjxray #5, so the packages carry zero
local patches), extended Artix-7 board coverage plus the Spartan-7 and
Zynq-7000 (PL) families, a declarative regression suite that gates every
package on all three platforms, and the automated build, validation and
release workflows.

**Fernando Mosquera ([Benitos](https://github.com/benitoss))**
contributed with Icestudio and verilog designs, feedback, testing, and real-world physical board tests.


## License

The Apio project itself is licensed under the GNU General Public License version 3.0 (GPL-3.0).
Pre-built packages may include third-party tools and components, which are subject to their
respective license terms.
