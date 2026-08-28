# demo-arty — upstream sources, our toolchain, nothing adapted

## What it probes

The blinky from openXC7/demo-projects for the Digilent Arty A7-35,
**exactly as upstream ships it**: their Verilog, their board XDC (real
`LOC` pins + `IOSTANDARD`), through our full flow on xc7a35tcsg324. This
is third-party sanity: every other test in the catalogue is ours, written
with knowledge of the framework's conventions; this one nobody wrote for
us.

Two things only this test (with `demo-basys3`) covers:

- **`LOC`-style constraints**: our generated XDCs use `PACKAGE_PIN`;
  upstream uses `set_property LOC` and no clock constraint — a different
  parser path in nextpnr's XDC frontend.
- **A part that is otherwise mostly idle**: xc7a35tcsg324 (the Arty
  package) gets exercised beyond the `constant` sweep.

## Why it exists

If a toolchain change breaks the demos the openXC7 community actually
starts from, our property tests may all pass while every newcomer's first
`make` fails. The sources are **locked by revision** in `regress/lock.json` (tree
fetched by `scripts/fetch-demos.sh` into `regress/external/`, never
committed); an unfetched tree reports SKIP with the fetch command — the
suite still runs everywhere without GitHub access (bit0 gets the tree by
rsync).

## Expected result

Routes and produces a bitstream; a 25-bit counter (`FDRE >= 25`) plus its
carry chain; trivial utilisation.

## Reading a failure

- **XDC/parse errors** — nextpnr's `LOC` constraint path regressed (our
  own tests would not see it).
- **Unroutable / placement errors on this part only** — package-specific
  pin data (csg324) regressed; compare with `demo-basys3` (cpg236).
- **FDRE < 25** — yosys changed how it maps the counter; recalibrate
  deliberately.
- **SKIP** — not a failure: run `scripts/fetch-demos.sh`.
