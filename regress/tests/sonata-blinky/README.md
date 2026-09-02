# sonata-blinky — a clock entering on a left-bank pad

## What it probes

A knight-rider blinky for the **lowRISC Sonata ONE** (`xc7a50tcsg324`): the
25 MHz board oscillator drives a 22-bit prescaler and one lit LED sweeps back
and forth across `usrLed[7:0]`. 66 LUTs, 31 flip-flops, one BUFG.

Not the counter, though. What this test pins down is the **clock's route from
the pad to the BUFG**.

`mainClk` is pad **P15**, which on this package is a clock-capable input in the
*left* I/O bank — it lands in `LIOI3_X0Y23`. Every other board test in this
suite (`demo-arty`, `demo-basys3`, `demo-zybo`, `demo-genesys2`,
`spartan7-blinky`, and the generated constraints everywhere else) clocks from a
pad whose dedicated route to the global network does not pass near
`HCLK_IOI3`. This one does, and `HCLK_IOI3` is the tile where prjxray's
coverage runs out: its `HCLK_IOI_IO_PLL_CLK*_DMUX` inputs from
`HCLK_IOI_I2IOCLK_*` are real, non-pseudo pips in `tile_type_HCLK_IOI3.json`,
they are **not** listed in `ppips_hclk_ioi3.db`, and `segbits_hclk_ioi3.db` has
no bits for them.

`constraints.xdc` is lowRISC's `data/pins_sonata.xdc` trimmed to `mainClk` and
`usrLed[7:0]`, plus the 25 MHz `create_clock` from
`data/synth_timing_common.xdc`, rewritten in the `set_property LOC` dialect the
rest of the suite uses.

## Why it exists

A place-and-route tool that lets its general router take one of those pips
produces a FASM that `fasm2frames` rejects outright:

```
FasmLookupError: Segment DB HCLK_IOI3, key
  HCLK_IOI3.HCLK_IOI_IO_PLL_CLK3_DMUX.HCLK_IOI_I2IOCLK_BOT1 not found
```

nextpnr-xilinx 0.9.3 does not, for two independent reasons —
`Arch::routeClock()` binds the dedicated CCIO → HCLK_CMT → CLK_HROW → BUFG path
`STRENGTH_LOCKED` before the general router runs, and
`Arch::setup_pip_blacklist()` (`xilinx/arch.cc`) fences off the neighbouring
unfuzzed clock-plumbing families. Both are hard won: the comments in
`setup_pip_blacklist` record clocks that died on silicon.

Measured on 2026-08-27: the himbaechel port
(`himbaechel-xilinx-porting`, `2212c004`) has neither, takes the regional
IOCLK/RCLK detour with `--router router2` and with the default router,
deterministically across eight seeds, and this design is what exposed it. It is
the coverage hole that let a first-contact blocker through: 20 comparable tests
ran green because none of them clocked from this bank.

## Expected result

Routes and produces a bitstream; `FDRE >= 30`, and the `bitstream` artifact is
what proves `fasm2frames` could look up every feature the routing used. With
`--router router1` the himbaechel port also passes, which is the workaround
that test failures here should be read against.

## Reading a failure

- **`fasm2frames` fails naming an `HCLK_IOI3` key** — the place-and-route under
  test reached the global clock network through undocumented `HCLK_IOI3` pips.
  That is the regression this test exists for: fix the router (a dedicated
  clock path, or a pip blacklist), not the database.
- **Fails while every other artix7 test passes** — suspect `xc7a50tcsg324`
  packaging or the left-bank IO tiles; `constant/xc7a50tcsg324` scopes it.
- **Fails at synthesis with an unknown port** — the design is board-specific
  (`mainClk`, `usrLed[7:0]`), unlike the portable `(clk, led)` tests; it goes
  with its own `constraints.xdc` and cannot be run against another part.
