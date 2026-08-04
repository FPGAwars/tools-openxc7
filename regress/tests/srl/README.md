# srl — shift registers in LUTs, not flip-flops

## What it probes

A 32-deep rotating shift register whose only observable bit is the last
one — exactly the shape yosys maps onto a single SRLC32E. An SRL is a LUT
acting as memory, so it is legal **only in a SLICEM**: this test
exercises that placement restriction on purpose, plus the SRL-specific
fasm features, with no cascade involved. Depth is deliberately capped at
32 so this test isolates the *single-SRL* path: the in-slice MC31
cascade has its own tests (`srl-cascade` at 128, `srl-cascade-deep` at
256) — three layers, each failing independently.

Note the deliberate symmetry with `hier`: there we defeat SRL mapping (an
SRL would leave no timing path and the test would go blind); here we rely
on it, and the primitives assertion keeps each test honest about which side
it is on.

## Why it exists

The SLICEM-only rule has already produced a real failure class upstream:
6b46121f added an unconditional guard precisely because "SA / legalisation
can strand a memory/SRL LUT in a SLICEL — surfacing much later as an
unroutable 'Pin DI1/WE of bel ... has no associated wire'". Until this
test, nothing in the suite ever created an SRL, so that entire code path —
inference, SLICEM placement, write/read fasm — ran with zero coverage.
(Its first run also flushed out that >32-deep chains had never worked —
see `srl-cascade/README.md` for that story.)

## Expected result

At least one SRLC32E, zero flip-flops from the register itself, a routed
bitstream, and trivial utilisation. fmax is n/a: the whole register lives
inside the SRL, so there are no FF-to-FF timing paths.

## Reading a failure

- **`SRLC32E: expected >=1, netlist has 0`** — yosys stopped inferring SRLs
  (check its version) and the test went blind; do not lower the expectation.
- **Routing fails with a DI/WE pin error** — the SLICEM guard failure mode:
  an SRL landed in a SLICEL. That is a placer/legaliser bug, and this test
  exists to catch exactly it.
- **`fasm2frames` rejects a feature** — SRL configuration features are less
  travelled than plain-LUT ones; suspect the database/pin bump.
