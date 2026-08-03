# fanout — one driver, 256 loads

## What it probes

A single toggling flip-flop whose output feeds an XOR into all 256 bits of
a shift structure: one net with 256 sinks. High-fanout distribution is a
*different* stress from congestion — the traffic all radiates from one
point, so what suffers is net buildout and the driver's timing, not channel
capacity. The congestion pair deliberately keeps its traffic point-to-point
so the two effects stay separable.

## Why it exists

Real designs are full of moderate-fanout control signals (resets, enables,
state bits), and the fanout dimension was completely absent from the suite:
every other test's nets have a handful of sinks. The timing model's fanout
term and the router's handling of a many-sink net tree get their first
guard here. Kept deliberately at 256 — big enough to matter, small enough
that a failure is attributable.

## Expected result

257 flip-flops (the driver plus the 256-bit structure), a routed bitstream,
and a reported fmax that reflects the wide XOR + distribution cost. The
fmax baseline is the interesting number to watch across bumps: fanout
handling changes show up here before anywhere else.

## Reading a failure

- **fmax drops sharply** — the fanout term of the timing model or the
  router's tree building regressed; this is the signal the test exists for.
- **Routing fails outright** — unusual for this size; suspect the same
  overuse mechanisms the congestion pair guards, then compare with them.
- **FF count off** — synthesis restructured the design; investigate before
  touching the expectation.
