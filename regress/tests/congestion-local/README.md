# congestion-local — the control leg of the congestion pair

## What it probes

192 blocks of a 64-bit rotate-XOR register (~12k LUTs and FFs, ~60% of an
xc7a35t). Every block reads two neighbour buses: a **ring** link (block
i+1, which keeps the whole design observable from block 0) and a **far**
link at `(i*MUL + ADD) mod N`. This leg sets `MUL=1, ADD=3`: the far links
are also neighbours, so all traffic is short-hop. Its metrics are the
control reading — what the router does at this utilisation when locality
is easy.

`congestion-scatter` is the SAME design with `MUL=61`: identical LUTs, FFs
and net count; only where the far links go changes. A regression is
therefore attributable to placement/routing, never to "more logic".

## Why it exists (as a pair)

Utilisation and routing stress are usually conflated. Here utilisation is
fixed and locality is the knob:

- `scatter` regresses while `local` holds → contended-channel handling;
- both regress together → something global (placer, timing model, costs).

High utilisation is also the regime where router2's rip-up/cost machinery
actually works — none of the small property tests reach it. `pnr_seconds`
carries real tolerances here (warn +30%, fail +100%): at this size, router
effort IS the signal.

## Two collapses this bench survived at birth (both caught by its own FDRE assertion)

1. **Multiplicative-only far map** (`i*STRIDE mod N`): block 0 always maps
   to itself (0·S = 0), detaching the other 191 blocks from `led` — the
   design synthesised to ONE block. Hence the ring for liveness.
2. **Symmetric reset**: with every register starting at zero, all blocks
   provably hold identical state forever (`rot(s)^s^s = rot(s)` for all at
   once) and yosys' opt_merge fused the 192 registers into one. Hence the
   distinct per-block SEED.

Both are worth remembering for any future scale bench: liveness needs a
connected observation path, and symmetry is an invitation to merge.

## Expected result

Routes; ~12.3k LUTs / 12.3k FFs (FDRE >= 12288 asserted); modest fmax; pnr
time set by the baseline of each platform.

## Reading a failure

- **This leg fails to route** — at ~60% with neighbour traffic, a serious
  router regression; scope with `scatter` and the small tests.
- **pnr_seconds explodes here but not in scatter** — suspect placer changes
  (spreading/legalisation) rather than the router.
- **FDRE below 12288** — one of the two collapses came back; check the far
  map and the seeds before anything else.
