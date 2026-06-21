# Windows (mingw) cross-compile spikes

Reference artifacts from the Windows native (`windows-amd64`) port investigation,
cross-compiled **from Linux** with `pkgsCross.mingwW64`. The production recipe
lives in `nix/windows/` (the toolchain produces a **byte-identical bitstream**
to macOS/Linux).

These `.nix` files were run on a Linux build host with local source trees (`./nixpkgs-src`,
`./nextpnr-src`, `./prjxray-src`, `./e2e/`) because the host could not reach `github.com`;
they are **reference recipes**, not drop-in flake outputs. The eventual production form is a
`windows-amd64` output added to `flake.nix` plus a Windows assembler analogous to
`openxc7-pack.py`.

## Files

- `nextpnr-xilinx-mingw.nix` — two-stage cross build of `nextpnr-xilinx.exe`
  (native `bbasm` → `ImportExecutables.cmake` → cross import). Workarounds: boost without
  zstd, native python3 interpreter, `mingw_w64_pthreads`, `BUILD_PYTHON=OFF`, and the
  **router2 `boost::container::flat_map` → `std::map` postPatch** (the flat_map's sorted
  invariant breaks on mingw → crash; std::map fixes it, no change on Linux).
- `prjxray-mingw.nix` — cross build of `xc7frames2bit`/`bitread`/`xc7patch`. Applies the two
  POSIX patches below + `-Wl,--allow-multiple-definition` (mingw explicit-template-instantiation).
- `openxc7-windows-assemble.nix` — assembles the package tree (exes + DLLs + chipdb + data).
- `prjxray-patches/` — **upstream-PR material** for f4pga/prjxray: `#ifdef _WIN32` ports
  (Linux path unchanged):
  - `memory_mapped_file.cc` — `mmap` → `CreateFileMapping`/`MapViewOfFile`.
  - `database.cc` — `glob` → `FindFirstFileA`/`FindNextFileA`.

## Upstream PRs to file (remove the workarounds)

- openXC7/nextpnr-xilinx: `bound_nets` `boost::container::flat_map` → `std::map` in
  `common/router2.cc` (or fix the mingw flat_map issue).
- f4pga/prjxray: the two `#ifdef _WIN32` ports above, and make `Configuration<Spartan6>`'s
  explicit instantiation `inline`/`extern template` (to drop `--allow-multiple-definition`).
