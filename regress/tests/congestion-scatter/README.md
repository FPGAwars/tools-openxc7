# congestion-scatter — the stress leg of the congestion pair

## What it probes

The exact same design as `congestion-local` — 192 × 64-bit rotate-XOR
blocks, ~60% of an xc7a35t, each reading a ring bus and a far bus — with
one change: the far map becomes `(61·i + 7) mod 192`. An affine map with
a large multiplier has high graph bandwidth: no placement can make the
ring AND the far links short at the same time (a plain stride would not
achieve this — `(i+S) mod N` is topologically still a ring, and a placer
may lay any ring out as a snake). Same LUTs, same FFs, same net count;
only the geometry of the traffic changes.

This is the closest thing the suite has to a router torture test, and the
regime (contended channels, rip-up and retry, cost negotiation) that none
of the small property tests ever reach.

## Why it exists

See `congestion-local/README.md` for the pair's design rationale. This leg
is the one expected to move first when router cost functions, congestion
handling or rip-up strategies change — with `local` as the control that
separates "router under contention" from "everything got slower".

The differential reading is the point:

| local | scatter | reading |
|---|---|---|
| OK | regressed | router contention handling |
| regressed | regressed | global (placer / timing / costs) |
| OK | fails to route | channel capacity handling collapsed |

## Expected result

Routes — slower than `local` in both pnr time and fmax, and that gap is
healthy and expected. `pnr_seconds` here is a coarse thrash detector (warn 2x, fail 4x —
wall-clock varies wildly across machines); the robust congestion signal
is the fmax gap between the two legs, which is deterministic.

## Reading a failure

- **Fails to converge with overused wires** — genuine channel-capacity
  regression (compare `carry64`/`widemux`, which guard the *pin-conflict*
  flavour of overuse; this one is the *capacity* flavour).
- **pnr_seconds past fail while local holds** — the router is thrashing
  under contention; bisect router changes first.
- **The scatter/local gap collapses to ~1×** — suspicious in the other
  direction: either placement got dramatically better (verify and
  celebrate) or the permutation stopped scattering (check STRIDE).
