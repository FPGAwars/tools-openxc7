# hier — a netlist that was never flattened

## What it probes

That nextpnr's JSON frontend handles a **hierarchical** netlist: two
instances of a submodule, with signals passing straight through their ports.
The expectation `modules >= 3` asserts the hierarchy actually survived
synthesis — if yosys ever flattened it, the test would still pass its flow
while quietly stopping to test anything.

`synth_xilinx` does **not** flatten by default, which is exactly why this
path matters: it is what users get.

## Why it exists

A field bug. `net_old_indices` never grew, so the first `merge_nets()` call
on a multi-module design died with `std::out_of_range: vector`. Every test we
had at the time was flat, so the crash reached users before it reached us.
The lesson is written into the suite's design: coverage comes from
*structural properties*, not from bigger designs.

The fix is a backport of the mainline nextpnr patch
(`frontend-hier-merge-nets`), and it was later retired when the version bump
brought it in from upstream — which is another reason to keep the test: it
guards behaviour that no longer has a local patch protecting it.

## Expected result

Routes and produces a bitstream. The netlist keeps three modules (the top
plus two parametrised `stage` instances) and 22 flip-flops — 12 + 10, the
two shift register widths.

## Reading a failure

- **`modules: expected >=3, netlist has 1`** — synthesis flattened the
  design. The test is no longer testing hierarchy; fix the design or the
  synthesis options rather than lowering the expectation.
- **The flow crashes inside nextpnr's frontend** — the original bug is back.
  Check whether a version bump lost the merge_nets fix.
- **Flip-flop count collapses** — the shift registers were mapped to SRLs.
  That happened during development when only the last bit of each register
  was observable; the design deliberately reduces the *whole* register to
  prevent it, because an SRL leaves no register-to-register path and the test
  would carry no timing signal at all.
