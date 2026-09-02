# bram — block RAM inference, placement and fasm

## What it probes

A 1024 x 16 memory with a registered read port, which synthesis maps to a
block RAM (asserted: at least one RAMB18E1 in the netlist). It then has to be
placed, routed, and turned into fasm features that `fasm2frames` accepts.

That last part is the least obvious and the most valuable: a BRAM emits a
large and intricate set of configuration features (widths, port modes,
initial contents), so this test covers far more of the prjxray database than
its size suggests.

## Why it exists

Block RAM is one of the three hard primitives of the fabric (with carry
chains and DSPs) and the one with the richest configuration surface. A
toolchain that routes LUTs perfectly can still be unable to emit a valid
BRAM: the failure would show up as `fasm2frames` rejecting a feature, or as a
bitstream that is structurally valid but functionally wrong.

The design writes and reads on the same clock and feeds the read data into
`led`, so the memory cannot be optimised away — an unread memory would simply
vanish during synthesis and the test would silently stop testing anything.

## Expected result

One RAMB18E1 in the netlist, a routed bitstream, and a high reported fmax
(~460 MHz on the reference part today) — a BRAM with registered outputs is
not the timing bottleneck in a design this small.

Utilisation stays tiny (~31 LUTs, 26 flip-flops) because the memory itself
lives in the block, not in fabric logic. A large jump in LUT count is the
signal that inference failed and the memory was built out of LUTs instead.

## Reading a failure

- **`RAMB18E1: expected >=1, netlist has 0`** — inference stopped working;
  the memory is now distributed RAM or plain logic. Check the yosys version
  before touching the expectation.
- **`fasm2frames` rejects a feature** — the interesting failure. It means
  nextpnr emitted a BRAM feature that the packaged prjxray database does not
  know, which usually points at a version bump where the database and the router
  disagree.
- **LUT count explodes** — same as the first case, seen from the metrics
  side: the memory was implemented in fabric.
