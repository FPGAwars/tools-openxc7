# srl-cascade-deep — the cascade beyond one slice

## What it probes

A 256-deep shift register: eight SRLC32Es, i.e. TWO full SLICEM cascades.
MC31 cannot leave a slice — there is no route from it to the general
fabric — so the link between the fourth and fifth SRL is physically
impossible as a Q31 link. The packer must move that boundary link onto
the ordinary **Q output with the read address tied to 31** (the same bit
Q31 carries, but fabric-routable) while keeping both 4-groups clustered
on the in-slice cascade. `srl-cascade` (128 bits, one slice) never
triggers this rewrite; this test exists for it.

Legal only because the boundary cell's Q is otherwise unused — when a
design also taps that segment at another address, the packer now emits a
clear, actionable error instead of an unroutable arc (that path is
untestable here since yosys never infers such a netlist from plain RTL).

## Why it exists

Second half of the `xc7-srl-cascade-packing` fix (see
`srl-cascade/README.md` for the history). The expected fasm: two SLICEMs,
each with `.SRL` on all four LUTs and the three in-slice `DI1MUX`
cascade features; the inter-slice hop routes through the fabric.

## Expected result

Routes; exactly 8 SRLC32E; the packer log reports one Q31 link moved to
Q[31]; fmax n/a (no FF-to-FF paths); fasm accepted end-to-end.

## Reading a failure

- **This fails while `srl-cascade` passes** — the Q31→Q boundary rewrite
  regressed (rewire logic, address tie, or the fold-into-existing-Q path).
- **Both fail** — the in-slice clustering or fasm feature naming broke;
  debug the 128 case first, it is the smaller reproducer.
- **SRLC32E ≠ 8** — yosys changed its shift-register mapping; recalibrate
  deliberately before touching the expectation.
