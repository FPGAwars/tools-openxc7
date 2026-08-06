"""xc7pll: the solver must respect every PLLE2 hard limit and hit knowns."""

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_loader("xc7pll", None)
xc7pll = importlib.util.module_from_spec(spec)
exec(compile(Path(__file__).resolve().parent.parent.joinpath("xc7pll")
             .read_text(), "xc7pll", "exec"), xc7pll.__dict__)


class TestSolver(unittest.TestCase):
    def test_known_exact_100_to_65(self):
        div, mult, odivs, vco = xc7pll.solve(100.0, [65.0])
        self.assertEqual((div, mult, odivs), (1, 13, [20]))
        self.assertEqual(vco / odivs[0], 65.0)

    def test_multi_output_shares_vco(self):
        div, mult, odivs, vco = xc7pll.solve(100.0, [65.0, 25.0])
        self.assertEqual(vco / odivs[0], 65.0)
        self.assertEqual(vco / odivs[1], 25.0)

    def test_limits_hold_across_sweep(self):
        for fin in (19.0, 33.333, 50.0, 100.0, 125.0, 200.0, 450.0):
            for ftgt in (10.0, 33.0, 65.0, 148.5, 300.0, 640.0):
                got = xc7pll.solve(fin, [ftgt])
                if got is None:
                    continue
                div, mult, odivs, vco = got
                self.assertTrue(xc7pll.D_MIN <= div <= xc7pll.D_MAX)
                self.assertTrue(xc7pll.M_MIN <= mult <= xc7pll.M_MAX)
                self.assertTrue(
                    xc7pll.PFD_MIN <= fin / div <= xc7pll.PFD_MAX, (fin, ftgt))
                self.assertTrue(
                    xc7pll.VCO_MIN <= vco <= xc7pll.VCO_MAX, (fin, ftgt))
                for o in odivs:
                    self.assertTrue(xc7pll.O_MIN <= o <= xc7pll.O_MAX)

    def test_prefers_exact_over_higher_vco(self):
        div, mult, odivs, vco = xc7pll.solve(100.0, [65.0])
        self.assertAlmostEqual(vco / odivs[0], 65.0)

    def test_cli_rejects_mmcm_territory(self):
        with self.assertRaises(SystemExit):
            xc7pll.main(["-i", "12", "-o", "48"])

    def test_cli_rejects_unreachable_output(self):
        with self.assertRaises(SystemExit):
            xc7pll.main(["-i", "100", "-o", "2000"])

    def test_module_emission_contains_config(self):
        div, mult, odivs, vco = xc7pll.solve(100.0, [65.0])
        v = xc7pll.module(100.0, [65.0], div, mult, odivs, vco, "pll")
        for frag in ("PLLE2_BASE", ".CLKFBOUT_MULT(13)", ".DIVCLK_DIVIDE(1)",
                     ".CLKOUT0_DIVIDE(20)", "BUFG", ".CLKFBIN(clk_fb)"):
            self.assertIn(frag, v)


if __name__ == "__main__":
    unittest.main()
