# srl-cascade — a known toolchain gap, kept on the record

## What it probes

A 128-deep shift register, which needs four SRLC32Es chained through the
dedicated MC31→DI cascade. **This is an expected-fail test** (`status:
"fail"`): it passes while the flow keeps failing, and trips the day the
flow succeeds — so the gap can never be silently fixed (or silently
believed fixed).

## Why it exists

Found on 2026-08-04 by the first SRL coverage this suite ever had, and
verified to be historic rather than a regression:

- **27727428 (the July pin)** dies at pack/arch level:
  `No wire found for port Q31`.
- **a9badf1d + #105 (current)** gets further — the port exists, packing
  succeeds — and dies at routing:
  `Failed to route arc ... C6LUT_MC31 -> ADI1MUX_OUT`, with the chained
  SRLs placed four rows apart. The MC31 cascade physically reaches only
  the adjacent slice, and nothing constrains the chain elements to be
  adjacent.

Every design inferring a shift register deeper than 32 (delay lines, FIR
pipelines, synchronisers with long depths) hits this. Users can work
around it with `srl_style` attributes or manual FF stages, but the
toolchain gives no useful diagnostic — just an unroutable arc.

Upstream-issue material: clean two-pin history, minimal reproducer, and
the likely fix direction (constrain chained SRLs into adjacent slices at
pack time, the same way carry chains are constrained).

## Expected result

The flow FAILS (currently at the MC31 routing arc) and the test therefore
reports OK. `led` stays driven through the final tap so synthesis cannot
optimise the chain away before it reaches the failure.

## Reading a "failure"

A failure of THIS test means the design **routed**: the cascade gap was
fixed. Do not just bump tolerances — verify on hardware if possible, flip
this into a positive test (drop `status: fail`, assert `SRLC32E >= 4`),
and retire the limitation note from the docs.
