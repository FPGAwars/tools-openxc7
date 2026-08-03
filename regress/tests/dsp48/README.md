# dsp48 — the DSP48E1 path and our timing model for it

## What it probes

A signed multiply-accumulate that synthesis maps onto a DSP48E1 slice
(asserted: the netlist must contain at least one), routed and reported with
timing. `metrics_present: fmax_mhz` guards that the timing report actually
produced a number — an empty clock table is a regression even when the
bitstream is fine.

## Why it exists

The DSP48E1 timing data was already in the chipdb (prjxray's `DSP_{L,R}.sdf`)
but nextpnr ignored it, so any design using a DSP reported a fantasy fmax.
We added `getPortTimingClass`/`getCellDelay` support that models the fully
combinational DSP (internal registers at zero) with a conservative
worst-case-per-arc table, and calibrated it against Vivado on the build
server.

The effect on a real design was large: a cascade of two DSPs went from a
reported 197 MHz to an honest 59 MHz. A silent regression here would not
break anybody's bitstream — it would just start lying about timing again,
which is far harder to notice. Hence a test whose primary signal is `fmax`.

## Expected result

One DSP48E1 in the netlist, a routed bitstream, and a reported fmax in the
low hundreds of MHz (~320 MHz on the reference part today).

Registered DSP configurations are still `TMG_IGNORE`, so this test covers the
combinational case only — which is the one that matters for the Icestudio
style of design that motivated the work.

## Reading a failure

- **`DSP48E1: expected >=1, netlist has 0`** — synthesis stopped inferring a
  DSP and mapped the multiplier to LUTs. The test is no longer exercising the
  DSP path; investigate the yosys version before touching the expectation.
- **fmax rises sharply** — the suspicious direction here. A jump back towards
  ~200 MHz suggests the DSP timing arcs are being ignored again.
- **fmax missing** — the timing walk aborted. Related failures to compare
  against: `widemux`, which guards the walk itself.
