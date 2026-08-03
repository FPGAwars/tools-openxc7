# pll — the clock management tile

## What it probes

A PLLE2_BASE instantiated with its feedback loop closed (CLKFBOUT→CLKFBIN),
its output taken through a BUFG into a counter clocked by the derived
50 MHz domain. Clock primitives are never inferred, so without an explicit
instantiation the whole CMT — PLL configuration fasm, the feedback route,
the BUFG tree from a non-pad source — has zero coverage.

## Why it exists

The clocking path has its own bug history in this tree: the upstream range
we ride includes "pack_clocking_xc7: keep a REAL MMCM CLKFBOUT->CLKFBIN
loop for free MMCMs", and a PLLE2+counter design was part of validating the
router reservation fix — this test makes that class of design a permanent
guard instead of a one-off. The PLL also emits a distinctive block of fasm
features (dividers, phase, lock) that nothing else in the suite touches.

## Expected result

Exactly one PLLE2_BASE, at least one BUFG, a routed bitstream. Yosys warns
about the floating-point CLKIN1_PERIOD parameter being passed as a string —
harmless and expected. The fmax report covers the input-clock domain;
timing of the derived domain is not asserted.

## Reading a failure

- **Packing/placement errors around the CMT** — the PLL landed somewhere
  invalid or its feedback could not be kept; check pack_clocking changes.
- **Routing fails on the feedback or BUFG net** — dedicated clock routing
  regressed; these nets cannot take general fabric detours.
- **`fasm2frames` rejects a PLL feature** — configuration encoding drifted
  from the database.
