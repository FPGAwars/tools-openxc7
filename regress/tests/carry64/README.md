# carry64 — long carry chains

## What it probes

A 64-bit counter and a 64-bit adder, which synthesis implements with the
fabric's dedicated CARRY4 primitives (asserted: at least 8 of them). Carry
chains are not ordinary logic: they must be placed in **vertically adjacent
slices**, because the carry signal propagates through a dedicated path
between them rather than through general routing.

So this test exercises a placement constraint the placer cannot violate, and
the arithmetic fasm features that go with it.

## Why it exists

Carry chains are where "the placer put the cells anywhere it liked" stops
being acceptable. A regression in chain placement does not usually produce a
wrong bitstream — it produces one that fails to route, or one whose timing
collapses because the chain got split across the die.

It is also the slowest design in the suite in fmax terms, which makes it the
best early-warning signal we have for timing regressions: it sits closest to
the edge.

Both registers are folded into `led` so neither the counter nor the adder can
be optimised away.

## Expected result

At least 8 CARRY4 cells (32 today: two 64-bit chains), 128 flip-flops
(64 + 64), and the **lowest fmax in the suite** — around 196 MHz on the
reference part. That low number is the point, not a problem.

## Reading a failure

- **fmax drops** — the most likely real regression: chains being split, or
  the timing model for the carry path changing. This test is the canary
  precisely because it has the least slack.
- **`CARRY4: expected >=8, netlist has 0`** — synthesis stopped using the
  dedicated carry logic and built adders out of LUTs. Utilisation would jump
  at the same time.
- **Routing fails** — suspect the vertical-adjacency constraint in placement
  rather than general congestion; this design is far too small to congest a
  35T part.
