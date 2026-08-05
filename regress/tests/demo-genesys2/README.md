# demo-genesys2 — a known gap, kept on the record (expected-fail)

**Status (2026-08-05): kintex7 is OUT of the manifest** — see below. This
test is the tripwire that fires when the whole chain finally works.

## The gap

The design routes; `fasm2frames` rejects the RIOB18 features
(`IBUFDS_BANK_GLUE`, `SSTL*.IN_DIFF`, `*.IN_ONLY`): the kintex7 HP-bank
differential-input bits were never fuzzed in the prjxray db. Genesys2 and
KC705 only have LVDS clocks, so kintex7 support without IBUFDS is a
broken promise — the family left the manifest and its boards left
apio-definitions until round 3 (upstream prjxray fuzzing/investigation).

## Original probe description

## What it probes

The upstream openXC7/demo-projects blinky for the Digilent Genesys2,
untouched, on `xc7k325tffg900` (the only speed grade the db carries is
-2 — the harness resolves it from the part dir). Beyond being the first
kintex7 coverage, this design enters through an **LVDS differential
clock** (`clk_p`/`clk_n` → IBUFDS), a clock-input path no other test in
the catalogue exercises.

## Why it exists

Batch-2 family expansion (ZedBoard + kintex7 ffg900). Everything
kintex7-specific runs for the first time here: its chipdb (462 MB bin,
the largest we ship), its prjxray-db, its tile mix. KC705 shares the
part; the ZedBoard footprint is covered by the constant sweep.

## Expected result

Routes and produces a bitstream; a counter (`FDRE >= 20`); IBUFDS
inferred for the clock pair.

## Reading a failure

- **Only this fails, artix7/zynq7 green** — kintex7-specific packaging
  or the IBUFDS path; check `constant/xc7k325tffg900` to scope which.
- **SKIP** — run `scripts/fetch-demos.sh`.
