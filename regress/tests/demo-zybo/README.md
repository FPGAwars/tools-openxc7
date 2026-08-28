# demo-zybo — the first zynq7 design through the toolchain

## What it probes

The upstream openXC7/demo-projects blinky for the Digilent Zybo Z7-10,
untouched (their Verilog, their board XDC), on `xc7z010clg400` — the
part that also powers the EBAZ4205. This is the PL-only zynq flow: the
bitstream configures the fabric; the PS7 boots on its own, exactly as
the upstream demo works on real hardware.

## Why it exists

First zynq7 coverage in the suite (added with the Core-3 family
expansion). Everything family-specific runs for the first time here:
zynq7 chipdb, zynq7 prjxray-db (segbits/part.yaml), gen-through-fasm
feature names of a different tile mix. Locked by revision in `regress/lock.json`,
fetched by `scripts/fetch-demos.sh`; absent tree reports SKIP.

## Expected result

Routes and produces a bitstream; a counter (`FDRE >= 20`); trivial
utilisation.

## Reading a failure

- **Only this fails, artix7 green** — zynq7-specific packaging (chipdb,
  db, fasm features); check `constant/xc7z010clg400` to scope.
- **SKIP** — run `scripts/fetch-demos.sh`.
