# tools-openxc7

> **Note:** Please **do not** open issues in this repository.
> For any questions, discussions, or bug reports, use the [main Apio repository](https://github.com/FPGAwars/apio).

Apio package with selected binaries from the [openXC7 project](https://github.com/openxc7):
an open source toolchain for **Xilinx 7-series FPGAs** (Artix-7 and friends).

This repository does not develop the toolchain itself — it **builds and packages**
it reproducibly with [Nix](https://nixos.org), publishes one tarball per platform,
and provides the scripts to install and use it, with or without
[apio](https://github.com/FPGAwars/apio).

## What is inside a package

| Component | Upstream | Role in the flow |
|---|---|---|
| `nextpnr-xilinx` | [openXC7](https://github.com/openXC7/nextpnr-xilinx) | Place & route, and FASM output |
| `xc7frames2bit`, `bitread`, `xc7patch` | [Project X-Ray](https://github.com/f4pga/prjxray) | Frames → bitstream, and bitstream inspection |
| `fasm2frames` + the `fasm` Python library | [openXC7 fasm](https://github.com/openxc7/fasm) | FASM → configuration frames |
| `chipdb/<part>.bin` | built here | Per-part device database used by nextpnr |
| `share/nextpnr/external/prjxray-db` | Project X-Ray database | Pin/part data (`part.yaml`, `package_pins.csv`, …) |

Synthesis is **not** part of this package: it comes from `yosys`, shipped by
[oss-cad-suite](https://github.com/FPGAwars/tools-oss-cad-suite).

## Supported platforms

| OS | Arch | Platform token | Status |
|---|---|---|---|
| Linux | x86_64 | `linux-x86-64` | ✅ built and published |
| macOS | Apple Silicon | `darwin-arm64` | ✅ built and published (native, ad-hoc signed) |
| Windows | x86_64 | `windows-amd64` | ✅ built and published (cross-compiled from Linux, validated under wine) |
| macOS | Intel | `darwin-x86-64` | ⛔ not built yet |
| Linux | aarch64 | `linux-aarch64` | ⛔ not built yet |

The last two tokens are recognized by the installer scripts, but no packages are
published for them yet, so installation would fail with a download error.

Packages coexist as assets of the same dated release:

```
apio-openxc7-linux-x86-64-<YYYYMMDD>.tgz
apio-openxc7-darwin-arm64-<YYYYMMDD>.tgz
apio-openxc7-windows-amd64-<YYYYMMDD>.tgz
```

## Supported FPGA parts

Every package ships a chipdb (and the matching prjxray database) for three
7-series families:

| Family | Device | Footprints | Boards (examples) |
|---|---|---|---|
| Artix-7 | xc7a35t | `cpg236`, `csg324`, `fgg484`, `ftg256` | Basys3, Arty A7-35, Cmod A7 |
| Artix-7 | xc7a50t | `csg324`, `fgg484` | |
| Artix-7 | xc7a100t | `csg324`, `ftg256`, `fgg484`, `fgg676` | Arty A7-100, Nexys |
| Artix-7 | xc7a200t | `fbg484` | |
| Spartan-7 | xc7s50 | `csga324` | Arty S7-50 |
| Zynq-7000 (PL) | xc7z010 | `clg400` | Zybo Z7-10, EBAZ4205 |
| Zynq-7000 (PL) | xc7z020 | `clg400`, `clg484` | Pynq-Z1/Z2, Arty Z7-20, Zybo Z7-20, ZedBoard |

Zynq support is **PL-only**: the toolchain produces the fabric bitstream
(loaded over JTAG); the ARM PS boots on its own. The Arty S7-25 cannot be
supported yet (`xc7s25` is not in the prjxray database), and Kintex-7 is
work in progress (its differential-input bits are missing upstream).

`chipdb-parts.json` is the **single source of truth** for that list: it is read by
the packer, by the Windows build and by the CI assertions. Adding a board whose
footprint already exists in the prjxray database is a one-line change there.

## Using the toolchain with apio (recommended)

[apio](https://github.com/FPGAwars/apio) downloads and installs this package for
you, wires the environment, and runs the whole flow. Board and FPGA definitions
live in [apio-definitions](https://github.com/FPGAwars/apio-definitions).

This repository is an **apio package**: apio is the supported way to install
and use it on every platform. If you want the openXC7 toolchain standalone,
use the upstream [openXC7](https://github.com/openXC7) project directly.

## Building the packages from source (developers)

The build is reproducible with **Nix** (locked flake). There is no
cross-compilation between Linux and macOS — each is built natively on its own
machine — while the Windows package **is** cross-compiled from Linux, because
Nix does not run on Windows.

### Linux / macOS (native)

```bash
nix develop .#pack                                   # packaging shell
python3.12 openxc7-pack.py                           # -> apio-openxc7-<platform>-<date>.tgz
```

The first `nix develop` builds the whole toolchain and takes a while (tens of
minutes); later ones take seconds. `nix develop` (without `.#pack`) gives the
full development shell; `.#pack` is the lighter profile the packer actually
needs.

Generating the chipdb is the slow part (one `bbaexport` per part, RAM hungry).
The `.bin` files are **platform independent and byte-identical**, so they can be
generated once and reused:

| Variable | Meaning |
|---|---|
| `OPENXC7_PACK_DATE` | Force the package date (`YYYY-MM-DD`), instead of today |
| `OPENXC7_CHIPDB_SEED` | Directory of prebuilt `.bin` files to reuse |
| `OPENXC7_CHIPDB_JOBS` | Parallel chipdb jobs (memory hungry — raise with care) |

> **Caveat:** when you bump the toolchain revisions, remove `dist/`
> before packing (`rm -rf dist`). Chipdb files built against a different
> revision are silently incompatible and the toolchain rejects them at runtime
> with an "internal IDs inconsistent" error.

### Windows (cross-compiled from Linux)

```bash
nix build .#packages.x86_64-linux.openxc7-windows-amd64
```

The result is the package **tree**; CI tars it with the release date. The
`nextpnr-xilinx.exe` embeds a Python interpreter, so `--post-route` scripts
(and therefore `apio report`) work exactly like on Linux/macOS.

## Validating a package

Everything the CI gates on is a script you can run locally, which is the point:
a release is only as trustworthy as the checks you can reproduce.

```bash
scripts/validate-package.sh apio-openxc7-linux-x86-64-20260731.tgz
scripts/validate-package.sh apio-openxc7-windows-amd64-20260731.tgz --wine
scripts/validate-package.sh <package.tgz> --parts "xc7a35tcpg236" --keep
```

It validates the package **inside its tarball** (never the freshly built tree)
and exits non-zero on any failure:

- the layout, and that every part of `chipdb-parts.json` ships its `.bin`;
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

The second layer is the **regression suite**: 21 declarative tests (one
folder + `test.json` each) that run real designs through the whole flow on
every packaged family — primitives, structural properties, a parametric
congestion pair, and the untouched upstream demo projects — and compare
fmax/utilisation/router-time against per-platform baselines:

```bash
scripts/fetch-demos.sh                     # locked third-party sources
scripts/regress.sh <package.tgz>           # the whole catalogue
scripts/regress.sh <pkg> --test srl --json report.json
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
| `linux-package.yml` | Builds + validates `linux-x86-64` (and owns the chipdb) |
| `darwin-package.yml` | Builds + validates `darwin-arm64` |
| `windows-package.yml` | Cross-builds + validates `windows-amd64` under wine |
| `build-pre-release.yaml` | Daily orchestrator (FPGAwars convention): builds the three only when there are new commits, then publishes |
| `promote.yml` | Manual dispatch: re-verifies a candidate, marks it stable + latest, opens the apio remote-config PR |
| `monitor-versions.yml` | Daily alarm: the latest promoted release and apio's remote-config must agree |

`build-pre-release.yaml` creates the release **only after every platform is
green**, as a dated **prerelease** (never "latest"), with the three tarballs,
their `SHA256SUMS`, and one gzipped `chipdb-<part>-<date>.bin.gz` per FPGA
plus a `chipdb-index-<date>.json` (the bins are platform-independent — these
per-FPGA assets back apio's upcoming on-demand loader). Old prereleases are
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
