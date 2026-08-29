# regress/ — regression suite

Answers a question the package gate cannot: **did this change make the
toolchain worse?** `scripts/validate-package.sh` proves a package builds valid
bitstreams; this suite compares *how good* those bitstreams are, and whether
the toolchain still behaves the way each test declares it should.

```bash
scripts/regress.sh --list                       # the catalogue (no toolchain needed)
scripts/regress.sh --explain bram               # what a test is for, in full
scripts/regress.sh <package-dir-or-tgz>         # run everything, compare vs baseline
scripts/regress.sh <package> --test bram --keep
scripts/regress.sh <package> --tier 1 --markdown report.md
scripts/regress.sh <package> --update-baseline  # record new reference values
```

Needs `yosys` on PATH, from the oss-cad-suite version recorded in `lock.json` — the same
one apio installs, so the numbers describe what users actually get.

## Adding a test

A test is a directory. Drop it in and it is picked up — no code to touch:

```
regress/tests/mydesign/
├── test.json     what is checked (machine-readable)
├── README.md     what it is for (required)
└── design.v
```

**The README is mandatory** — the harness refuses to load a test without one.
A declaration says *what* is asserted; the README says what the test is for,
what a good result looks like, and how to read a bad one. Four sections:

| Section | Content |
|---|---|
| What it probes | The mechanism under test, and what each expectation pins down |
| Why it exists | The bug, risk or property behind it — the part nobody can reconstruct later |
| Expected result | What a healthy run produces, with today's reference numbers |
| Reading a failure | Each plausible failure and what it points at |

Keep the machine-readable facts in `test.json` and the narrative in the
README, so the two cannot contradict each other. `--explain <test>` prints
it.

The design exposes `(input clk, output led)` and the declaration can be two
lines, because everything else has a default:

```json
{
  "description": "What this is",
  "exercises": ["what it guards"]
}
```

Defaults: `top` = the directory name · `sources` = the `.v` files in it ·
`parts` = one representative part · constraints generated from the prjxray
database · the whole flow runs · metrics are tracked against the baseline.

### Declaration reference

| Key | Default | Meaning |
|---|---|---|
| `description` | *(required)* | One line, shown in reports |
| `exercises`, `why` | — | What it guards, and the story behind it |
| `tier`, `tags` | `1`, `[]` | Selection with `--tier` / `--tag` |
| `sources`, `top` | `*.v`, dir name | Inputs |
| `parts` | `"default"` | A list, or a group: `default`, `artix7`, `all` |
| `constraints` | `"auto"` | Generated from the database, or a file in the test directory |
| `xdc_extra` | `[]` | Extra constraint lines appended (portable across parts) |
| `synth.opts` | `""` | Extra yosys options |
| `parameters` | `{}` | Verilog parameters (`chparam`) — one parametrised design can back several tests |
| `nextpnr.args`, `nextpnr.router` | `[]`, `router2` | Extra pnr options |
| `flow` | `bitstream` | Stop at `synth`, `pnr`, `fasm` or go all the way |
| `expect` | `{status: pass}` | See below |
| `metrics.track`, `metrics.tolerances` | `true`, defaults | Baseline comparison |

### Expectations

| Key | Example | Checks |
|---|---|---|
| `status` | `"fail"` | Negative tests: the flow *must* fail |
| `log_contains` / `log_absent` | `["ignoring virtual clock"]` | Regex over the whole flow log (case-insensitive — a bare `ERROR` matches Python's `ImportError` in the benign Windows fasm-parser fallback; use `\bERROR:` for tool errors) |
| `primitives` | `{"DSP48E1": ">=1"}` | What synthesis inferred, counted on the netlist |
| `modules` | `">=3"` | Modules surviving synthesis, i.e. hierarchy is intact |
| `artifacts` | `["bitstream"]` | Produced and non-empty |
| `metrics_present` | `["fmax_mhz"]` | The metric was reported at all |

Unknown keys are a hard error: a typo must never turn into a check that
silently does nothing.

## Two rules that shape everything here

**1. Every design has the same interface: `(input clk, output led)`.**
That is what makes a test portable across every part in the manifest — the
constraints come from the prjxray database, so no test carries board-specific
pin assignments. Designs differ in their *internals*, never in their pinout,
and each funnels its state into `led` so nothing can be optimised away. The
board tests are the deliberate exception: `demo-*` and `sonata-blinky` bring
their board's own XDC and run on that board's part only, because there the
pinout *is* what is being tested.

**2. Baselines are per platform, never compared across platforms.**
Measured fact: each nextpnr binary is deterministic run to run, but placement
diverges between the linux, darwin and mingw binaries for anything
non-trivial, and yosys/abc are not cross-platform deterministic either. So
"same test, same part, same platform, versus last time" is signal; "linux
versus darwin" is noise. (The chipdb `.bin` *is* byte-identical everywhere —
that one is asserted by the release pipeline.)

## What the catalogue covers, and why it is built this way

Tests are chosen by the **property** they exercise, not by size. That is not a
preference, it is what our own bug history says: every regression this
toolchain has actually suffered was caught by a small, targeted design — the
most valuable one of all (the global constant node, which closed three
upstream issues) reproduced with `assign led = 1'b1`. The single coverage gap
we did suffer, a crash in the hierarchical frontend, happened because every
test we had was *flat*: a missing structural property, not a missing large
design. A big opaque design would buy realism at the cost of diagnosis — when
"fmax dropped 8%" comes out of a CPU, you are left bisecting it.

| Group | Tests |
|---|---|
| Primitives | `carry64`, `bram`, `dsp48`, `widemux`, `srl`, `srl-cascade`, `srl-cascade-deep`, `lutram`, `pll`, `tristate` |
| Structural properties | `hier` (never flattened), `constant` (constant straight to a pad, run across every part), `fanout` (one driver, 256 loads), `carry-const-di` (a CARRY4 whose DI inputs are constant GND while a mid-chain CO fans out to the fabric — the packing class Hans Baier bisected to PR #105, graduated to a positive test at the 2026-08-11 revision bump; its tight timeout stays as a hang-class guard) |
| Behaviour parity | `vclk` (a virtual clock must warn, not crash, and still report timing) |
| Clock entry | `sonata-blinky`: a board clock arriving on a *left*-bank clock-capable pad (P15 of the lowRISC Sonata ONE) and reaching a BUFG. Every other board test clocks from a pad whose dedicated path stays clear of `HCLK_IOI3`, where prjxray's coverage runs out; a P&R that routes through those unfuzzed pips emits a feature `fasm2frames` cannot look up, and this is the test that says so |
| Family coverage | `spartan7-blinky` (a 24-bit counter on `xc7s50csga324`, the Arty S7-50 part — ours, because upstream's spartan7 demos are DDR3/litex projects rather than smoke material) and `demo-zybo` (the untouched upstream Zybo Z7-10 blinky on `xc7z010clg400`, the PL-only zynq flow). Each is the first design of its family through the toolchain, so the family's chipdb, prjxray-db and fasm feature names run at all |
| Known gaps, on the record | `demo-genesys2` (tagged `xfail`): the Genesys2 blinky routes, then `fasm2frames` rejects the kintex7 RIOB18 differential-input features (`IBUFDS_BANK_GLUE`, `SSTL*.IN_DIFF`, `*.IN_ONLY`) — never fuzzed in the prjxray database. Kintex-7 left the manifest on 2026-08-05 over exactly that, so today the test fails earlier still (no chipdb for the part). It is the tripwire that trips when the whole chain finally works: then it PASSES, the guard fires, and the family can come back. (`srl-cascade` was the other one and graduated to a positive test when the `xc7-srl-cascade-packing` patch closed its gap.) |
| Scale | the `congestion-local` / `congestion-scatter` pair: ~60% utilisation with routing locality as the ONLY knob (same design, different `STRIDE`), so a regression separates "router under contention" from "everything got slower" |
| Third-party sanity | `demo-arty`, `demo-basys3` (and `demo-zybo`, `demo-genesys2` above): the openXC7/demo-projects blinkies untouched (their Verilog, their board `LOC` XDCs), locked by revision in `lock.json` and fetched by `scripts/fetch-demos.sh` — absent tree reports SKIP, never a gate |

## What is compared

| Metric | Meaning | Default tolerance |
|---|---|---|
| `fmax_mhz` | Worst clock from the post-route timing report | −5% fails |
| `luts`, `ffs`, `brams`, `dsps` | Utilisation, counted from the bound bels | +10% warns, +20% fails |
| `pnr_seconds` | Router+placer wall time | informational (machine-dependent); congestion pair opts into 2x/4x thrash detection |
| `bit_bytes` | Bitstream size | any change warns |

Baselines live in `baselines/<platform>.json` and are only refreshed with
`--update-baseline`, in the same change that moved the numbers: the baseline
diff *is* the regression report a human reviews.

## How it is put together

```
harness/spec.py     the declaration schema, its defaults and its validation
harness/pkg.py      the package under test and how to invoke its tools
harness/flow.py     runs the flow; reports what happened, judges nothing
harness/checks.py   one function per expectation, in a registry
harness/metrics.py  numbers worth tracking, and the baseline comparison
harness/reporting.py console, JSON and markdown renderings
```

Adding a test never touches code; adding a new *kind* of expectation is one
function in `checks.py` plus its key in `spec.EXPECT_KEYS`. Only the standard
library is used, so the suite runs on a laptop, on the build server without
internet access, and in CI without installing anything.
