# srl-cascade — the in-slice MC31 cascade, once a known gap

## What it probes

A 128-deep shift register: four SRLC32Es chained through the dedicated
Q31→D cascade. The MC31 wire that carries it only exists **inside** a
SLICEM — the cascade muxes run top-down D→C→B→A (`xDI1MUX ← (x+1)MC31`)
— so the packer must place the whole chain in ONE slice, head at D6LUT,
exactly like a carry chain. The expected fasm is characteristic: one
SLICEM with `.SRL` on all four LUTs and the three cascade features
`ALUT.DI1MUX.BDI1_BMC31`, `BLUT.DI1MUX.DI_CMC31`, `CLUT.DI1MUX.DI_DMC31`.

## Why it exists

**This never worked before the `xc7-srl-cascade-packing` patch** (found
2026-08-04 by this suite's first SRL coverage, fixed the same day):

- the July pin (27727428) died at pack/arch level:
  `No wire found for port Q31`;
- the a9badf1d pin mapped Q31→MC31, so packing succeeded — but nothing
  constrained the chain, HeAP scattered it across rows, and router2
  correctly reported the cascade arc unroutable
  (`... C6LUT_MC31 -> ... ADI1MUX_OUT`);
- the fasm emitter then still wrote bare site-wire names (`BMC31`),
  which fasm2frames rejects — prjxray names the shared mux leg after
  both signals riding it (`BDI1_BMC31`, …), because the LUTRAM
  write-data broadcast and the SRL cascade share one config bit.

The fix (cluster constraints in `pack_srls()` + the fasm feature names)
lives in `nix/patches/xc7-srl-cascade-packing.patch`, upstream-PR
material for openXC7/nextpnr-xilinx. This test is the guard that it
stays fixed. `srl-cascade-deep` covers the >128-bit continuation.

## Expected result

Routes; exactly 4 SRLC32E, no FDRE for the register body; fmax n/a (the
whole register lives in SRLs — no FF-to-FF paths, same as `srl`); fasm
accepted end-to-end (`fasm2frames` proves the cascade features are real
chipdb features).

## Reading a failure

- **`No wire found for port Q31`** — the Q31→MC31 port mapping regressed.
- **Unroutable `MC31 → …DI1MUX` arc** — the packer cascade clustering
  regressed (chain scattered across slices again).
- **fasm2frames rejects a `DI1MUX` feature** — the feature-name
  translation regressed (bare site-wire name emitted).
- **SRLC32E ≠ 4** — yosys changed its shift-register mapping; recalibrate
  deliberately before touching the expectation.
