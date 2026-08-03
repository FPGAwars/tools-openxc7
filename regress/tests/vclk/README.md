# vclk — a virtual clock must warn, not crash

## What it probes

An XDC that declares a clock with **no physical pin behind it**
(`create_clock -name VIRTUAL_c1` with no `get_ports`), which is perfectly
legal in vendor flows and appears in real board constraint files. The
toolchain must ignore it with a warning and carry on:

- the log contains `ignoring virtual clock`;
- the log contains no assertion or abort message;
- timing is still reported (`fmax_mhz` present), i.e. the clock table did not
  come back empty.

The design itself is a plain counter on purpose — what is under test is the
constraints path, not the logic.

## Why it exists

A user's board XDC contained a virtual clock and the flow died on it. The fix
had to do two things, and only one of them is obvious: stop crashing, *and*
keep the per-clock timing report populated, because that report is what
`apio report` reads. A fix that merely avoided the crash while leaving the
clock table empty would have looked green in a bitstream-only test.

This expectation used to live hand-written inside
`.github/workflows/windows-package.yml`, so it only ever ran under wine. It
is now a declarative test and runs on every platform — which is where it
belongs, since nothing about it is Windows-specific.

## Expected result

Routes and produces a bitstream, warns about the virtual clock, and reports
an fmax (~329 MHz on the reference part today).

## Reading a failure

- **The warning is missing** — either the constraint was silently swallowed
  (bad: users get no signal that part of their XDC was ignored) or the
  wording changed. If the wording changed upstream, update the expectation
  and say so in the commit message.
- **`Assertion` or `terminate called` in the log** — the original crash is
  back.
- **fmax missing** — the crash was fixed but the clock table is empty again;
  `apio report` would show nothing. Compare with `widemux`, which guards the
  timing walk from a different angle.
