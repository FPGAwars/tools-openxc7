# srl — shift registers in LUTs, not flip-flops

## What it probes

A 128-deep rotating shift register whose only observable bit is the last
one — exactly the shape yosys maps onto SRL primitives (asserted: at least
four SRLC32E, 128/32). An SRL is a LUT acting as memory, so it is legal
**only in a SLICEM**: this is the one test that exercises that placement
restriction on purpose, plus the SRL-specific fasm features.

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

## Expected result

Four SRLC32E, zero flip-flops from the register itself, a routed bitstream,
and trivial utilisation. fmax is high and not the point.

## Reading a failure

- **`SRLC32E: expected >=4, netlist has 0`** — yosys stopped inferring SRLs
  (check its version) and the test went blind; do not lower the expectation.
- **Routing fails with a DI/WE pin error** — the SLICEM guard failure mode:
  an SRL landed in a SLICEL. That is a placer/legaliser bug, and this test
  exists to catch exactly it.
- **`fasm2frames` rejects a feature** — SRL configuration features are less
  travelled than plain-LUT ones; suspect the database/pin bump.
