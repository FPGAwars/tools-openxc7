# carry-const-di — Hans Baier's const-DI class, GRADUATED (expect: pass)

> Until the a70ae4a8 revision bump (2026-08-11) this was an expected-fail
> guard for a known packer gap. The carry-O relocation transform (Hans)
> plus the split/legaliser fix series (ours, upstream PRs) fixed the
> class; the guard tripped "loudly" during validation exactly as
> designed, and the test now expects the flow to complete. The tight
> timeout stays: on a regression this must fail FAST, not freeze CI.
> Original gap description below, kept for the record.

## What it probes

A CARRY4 whose DI inputs are constant GND while a mid-chain CO fans out
to the fabric (two users), in a design with other GND consumers. The
packer serves the chain's DI from the **design-wide** `$PACKER_GND_NET`
feed-through LUT — one multi-user buffer that can only live in one
slice. Wherever it lands, that slice's 5LUT output has many fabric
users, which conflicts with the CO output-mux requirement: the (correct)
validity check restored by PR #105 rejects every candidate tile.

On the current revision this manifests as the ORIGINAL failure mode — an
infinite hang in `legalise_placement_strict` — which is why this test
carries a tight `timeout` (the harness feature this class forced us to
add). On toolchains with the upstream fail-fast guards (369038ed,
4a3d7e12) it fails fast with "Unable to find legal placement" instead.

## Why it exists

Bisected and root-caused upstream by **Hans Baier** on
`demo-projects/ddr3-test-arty-s7` (xc7s50, comparison-style $alu chains:
const DI, dead sums, carry-out into fabric); reported to us directly
with full evidence. Disabling the validity check is NOT the fix — the
placement it would allow is genuinely unroutable (15 overused wires).
The intended fix is **packer-side**: a dedicated single-user const
feed-through LUT per chain slice, cluster-constrained like the existing
S feed-throughs, so shared constant buffers can never land in chain
slices. Our `carry64` test never caught this: its sums are live.

## Expected result

The flow FAILS (currently: pnr times out on the legalise hang; after a
revision bump with the fail-fast guards: unplaceable error) and the test
therefore reports OK.

## Reading a "failure"

A failure of THIS test means the design **placed and routed**: the
packer fix landed. Flip it to a positive test (drop `status: fail`,
assert `CARRY4 >= 1`), and check whether the timeout can return to the
default.
