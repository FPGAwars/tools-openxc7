# Tools-openxc7

> **Note:** Please **do not** open issues in this repository.
> For any questions, discussions, or bug reports, use the [main Apio repository](https://github.com/FPGAwars/apio).

Apio package `openxc7`: the [openXC7](https://github.com/openXC7) toolchain for
Xilinx 7-series FPGAs (`nextpnr-xilinx`, prjxray, `fasm2frames` and the chipdb),
repackaged from the releases of
[toolchain-openxc7-releases](https://github.com/cavearr/toolchain-openxc7-releases),
the way [tools-oss-cad-suite](https://github.com/FPGAwars/tools-oss-cad-suite)
repackages the YosysHQ oss-cad-suite.

## Releases

The `build-pre-release` workflow runs daily (and by hand). It downloads the
toolchain release named by `OPENXC7_RELEASE_TAG` in
`.github/workflows/build-pre-release.yaml`, checks it against its
`SHA256SUMS`, and publishes a pre-release with six assets:

| Asset | |
|---|---|
| `apio-openxc7-<platform>-<YYYYMMDD>.tgz` | The package for `linux-x86-64`, `darwin-arm64` and `windows-amd64`: the toolchain tarball as is, plus apio's `BUILD-INFO.json` (the toolchain's own is kept as `TOOLCHAIN-BUILD-INFO.json`) |
| `XILINX-PARTS-INDEX.json` | The parts index of the toolchain release (also at the root of each package) |
| `BUILD-INFO.json` | The build info of the release |
| `SHA256SUMS` | SHA-256 of the other five assets |

Pre-releases are deleted after a few days. The `make-pre-release-stable`
workflow checks a release with `scripts/asset-check.sh` and makes it stable
(and, optionally, the latest release). apio's remote-config names a stable
release.

## Bumping the toolchain

Set `OPENXC7_RELEASE_TAG` to a newer **stable** release of
toolchain-openxc7-releases (the workflow refuses a pre-release). Each
toolchain release says which YosysHQ oss-cad-suite tag it was validated with
(`yosys-release-tag` in its `BUILD-INFO.json`); the package carries the same
value, and apio checks at run time that its oss-cad-suite package has it too.

`scripts/check-versions.sh` compares that yosys tag with the one of the
oss-cad-suite release apio's remote-config installs, and says when the
toolchain repo has a newer latest release.

## Development

* `python -m pytest tests` tests `.github/workflows/build.py`.
* `README-archived.md` is the original documentation of this repo, from
  when it built the toolchain itself.

## License

The Apio project itself is licensed under the GNU General Public License version 3.0 (GPL-3.0).
Pre-built packages may include third-party tools and components, which are subject to their
respective license terms.
