# regress/ — regression suite

Answers a question the package gate cannot: **did this change make the
toolchain worse?** `scripts/validate-package.sh` proves a package builds
valid bitstreams; this suite compares *how good* those bitstreams are
against a recorded baseline.

```bash
scripts/regress.sh <package-dir-or-tgz>                  # compare vs baseline
scripts/regress.sh <package> --design bram --part xc7a35tcpg236
scripts/regress.sh <package> --update-baseline           # record a new baseline
```

## How it is organised

| Path | What it is |
|---|---|
| `designs/<name>/design.v` | A self-contained design exercising one part of the toolchain |
| `designs/<name>/meta.json` | What it is for, its default parts and synthesis options |
| `baselines/<platform>.json` | Recorded metrics, one file per platform |
| `lock.json` | Pinned external inputs (oss-cad-suite, demo-projects, apio) |
| `harness.py` | The runner: flow, metric extraction, comparison |

## What the catalogue covers, and why it is built this way

Designs are chosen by the **property** they exercise, not by size. That is not
a preference, it is what our own bug history says: every regression this
toolchain has actually suffered was caught by a small, targeted design — the
most valuable one of all (the global constant node, which closed three
upstream issues) reproduced with `assign led = 1'b1`. The single coverage gap
we did suffer, a crash in the hierarchical frontend, happened because every
test we had was *flat*: a missing structural property, not a missing large
design. So a big opaque design would buy realism at the cost of diagnosis —
when "fmax dropped 8%" comes out of a CPU, you are left bisecting it.

| Group | Designs |
|---|---|
| Primitives | `carry64`, `bram`, `dsp48`, `widemux` |
| Structural properties | `hier` (never flattened), `constant` (constant straight to a pad) |
| Scale | *(pending)* parametrised designs that push utilisation into the congested regime, where routing behaves differently |
| Third-party sanity | *(pending)* the Artix-7 blinkies from openXC7/demo-projects, pinned in `lock.json` |

## Two rules that shape everything here

**1. Every design has the same interface: `(input clk, output led)`.**
That is what makes a design portable across every part in the manifest — the
constraints are generated from the prjxray database (`e2e/gen_xdc.py`), so no
design carries board-specific pin assignments. Designs differ in their
*internals* (BRAM, DSP, carry chains, …), never in their pinout. Each one
funnels its internal state into `led` so that nothing can be optimised away.

**2. Baselines are per platform, never compared across platforms.**
Measured fact: each nextpnr binary is deterministic run to run, but placement
diverges between the linux, darwin and mingw binaries for anything
non-trivial, and yosys/abc are not cross-platform deterministic either. So
"same design, same part, same platform, versus last time" is a signal; "linux
versus darwin" is noise. (The chipdb `.bin` *is* byte-identical everywhere —
that one is asserted by the release pipeline.)

## What is compared

| Metric | Meaning | Default tolerance |
|---|---|---|
| `fmax_mhz` | Worst clock from nextpnr's post-route timing report | −5% fails |
| `luts`, `ffs`, `brams`, `dsps` | Utilisation, counted from the bound bels | +10% warns, +20% fails |
| `pnr_seconds` | Place & route wall clock | ×1.5 warns (never fails: runners vary) |
| `bit_bytes` | Bitstream size | any change warns |

A design also fails outright if the flow does not complete: router2 must not
crash, the post-route script must run (that is the `apio report` path),
`fasm2frames` must accept every feature emitted, and the bitstream must not
be empty.

Baselines are only refreshed with `--update-baseline`, and that refresh
belongs in the same pull request as the change that moved the numbers: the
baseline diff *is* the regression report a human reviews.
