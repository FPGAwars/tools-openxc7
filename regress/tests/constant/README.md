# constant — a constant driving a pad, with nothing in between

## What it probes

The path from the global constant network (VCC/GND) to an output pad. The
design is one line of logic — `assign led = 1'b1` — so if it fails, nothing
about the user's design is to blame: the toolchain cannot route a constant.

It runs across **every part in the manifest** (11 today), unlike the other
tests, because the bug it guards behaved differently per part and per
placement.

The flip-flop toggling on `clk` is not part of the test: it only keeps the
clock port alive through synthesis, so the generated constraints (which
assign both pads) stay valid. `led` remains driven by the constant.

## Why it exists

This is the reproducer of the most valuable bug this project has found.
`bbaexport` built the global VCC/GND node out of column `x=0` wires only,
while the pseudo-driver bel that feeds it can be placed in any tile. A driver
placed outside column 0 could therefore only reach its own row, and
`assign led = 1'b1` failed to route on **every** part, with every seed.

The fix (a nix patch to `bbaexport`, so the global node spans every tile)
closed three open upstream issues at once. It also costs ~0.5 MB per chipdb
`.bin`, which is why a regression here would be tempting to "optimise" away.

## Expected result

Routes and produces a bitstream on all 11 parts. Utilisation is trivially
small and constant: 1 LUT, 1 flip-flop. `fmax` is meaningless here (there is
no real timing path) — it is recorded, but nothing depends on it.

The metric worth watching is `pnr_seconds`, which scales with part size and
is a cheap smoke signal for chipdb loading across the whole manifest.

## Reading a failure

- **Routing fails on some parts but not others** — the classic shape of the
  original bug: the global node does not span the fabric. Suspect any change
  to `bbaexport`, to the chipdb generation, or a pin bump that dropped the
  patch.
- **Routing fails everywhere** — more likely a general breakage; check the
  other tests before blaming the constant network.
- **`fasm2frames` rejects a feature** — the constant path emits very few fasm
  features, so this points at the prjxray database rather than at placement.
