# tristate — the output pad's third state

## What it probes

A `1'bz` assignment on the output port, which yosys turns into an OBUFT
(asserted: exactly one, replacing the plain OBUF every other test uses).
This is the only test that configures the tristate control path of an IOB.

## Why it exists

Every other design drives its pad unconditionally, so the T-input side of
the IOB — its packing rules, its fasm bits — had zero coverage. Tristate
pads are common in real designs (shared buses, bidirectional pins on
boards), and yosys itself warns that its tri-state support is limited: a
regression on this path is plausible on either side of the flow, and
without this test it would reach a user's board first.

## Expected result

One OBUFT, a routed bitstream, and yosys' "limited support for tri-state
logic" warning in the synthesis log — expected, not a failure. Utilisation
is trivial; fmax is not the point.

## Reading a failure

- **`OBUFT: expected 1, netlist has 0`** — inference changed (the design
  degenerated to a plain OBUF and the test went blind) or the high-Z was
  optimised out; check the yosys version.
- **Packing error naming the IOB or BEL** — the OBUFT did not fit the
  pack_io rules; compare with upstream issue #98, which lives in exactly
  that pass.
- **`fasm2frames` rejects an IOB feature** — the tristate configuration
  bits drifted from the database.
