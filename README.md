# tools-openxc7

> **Note:** Please **do not** open issues in this repository.
> For any questions, discussions, or bug reports, use the [main Apio repository](https://github.com/FPGAwars/apio).

**A packaging repository of the [apio](https://github.com/FPGAwars/apio)
ecosystem.** It produces the apio package `openxc7`, the way
[tools-oss-cad-suite](https://github.com/FPGAwars/tools-oss-cad-suite)
produces the `oss-cad-suite` package: it takes a release made elsewhere and
republishes it in the form apio installs. It builds no software and runs no
tests of the toolchain.

The toolchain itself, the [openXC7](https://github.com/openXC7) toolchain for
Xilinx 7-series FPGAs (`nextpnr-xilinx`, prjxray, `fasm2frames` and the
chipdb), is built, validated and released by
**[toolchain-openxc7-releases](https://github.com/cavearr/toolchain-openxc7-releases)**,
today under cavearr and on its way to the openXC7 organisation. That is the
repository for anything about the toolchain: what a release contains, which
parts it supports, how it is validated, how to install it without apio. When
it moves, this repository changes one literal (`OPENXC7_REPO`).

## What this repository does

Every day (and on demand) `build-pre-release` takes the toolchain release
named by `OPENXC7_RELEASE_TAG` in
`.github/workflows/build-pre-release.yaml`, downloads its three platform
tarballs, checks them against the release's `SHA256SUMS`, and publishes a
pre-release with apio's six assets:

| Asset | |
|---|---|
| `apio-openxc7-<platform>-<YYYYMMDD>.tgz` | The package for `linux-x86-64`, `darwin-arm64` and `windows-amd64`: the toolchain tarball as is, plus apio's `BUILD-INFO.json` (the toolchain's own is kept as `TOOLCHAIN-BUILD-INFO.json`) |
| `XILINX-PARTS-INDEX.json` | The parts index of the toolchain release (also at the root of each package) |
| `BUILD-INFO.json` | The build info of the release: apio's fields plus the toolchain release it repackages |
| `SHA256SUMS` | SHA-256 of the other five assets |

`yosys-release-tag` is copied from the toolchain release: apio checks at run
time that its `oss-cad-suite` package names the same YosysHQ release.

Pre-releases are deleted after a few days; a release is kept by marking it
stable, as with the other apio packages. apio's remote-config names a stable
release of this repository.

## What it does not do

- Build, test or patch the toolchain. toolchain-openxc7-releases does, with
  its own CI: package gate, multi-part end-to-end and regression suite on
  the three platforms, before any release is published.
- Choose versions of the tools. A release of this repository carries exactly
  what the toolchain release it names carries.
- Publish anything apio does not install.

## Bumping

Set `OPENXC7_RELEASE_TAG` to a newer stable release of
toolchain-openxc7-releases. The toolchain release says which YosysHQ
oss-cad-suite it was validated with, and apio's `oss-cad-suite` package has
to name the same one: apio checks it at run time.

## History

Until 2026-10-01 this repository built the toolchain itself; that history is
in the git log, and `README-archived.md` is its original documentation.

## License

The Apio project itself is licensed under the GNU General Public License version 3.0 (GPL-3.0).
Pre-built packages may include third-party tools and components, which are subject to their
respective license terms.
