// A PLLE2_BASE with its feedback loop, driving a counter through a BUFG.
// Clock primitives are instantiated, never inferred, so this is the one
// test that exercises the clock-management tile end to end.
module pll (
    input  wire clk,
    output wire led
);
    wire fb;
    wire clk_pll;
    wire clk_slow;
    wire locked;

    PLLE2_BASE #(
        .CLKIN1_PERIOD(10.0),      // constraints drive clk as ~100 MHz
        .CLKFBOUT_MULT(8),         // VCO 800 MHz, inside the xc7 range
        .CLKOUT0_DIVIDE(16)        // 50 MHz out
    ) pll_i (
        .CLKIN1(clk),
        .CLKFBIN(fb),
        .CLKFBOUT(fb),
        .CLKOUT0(clk_pll),
        .RST(1'b0),
        .PWRDWN(1'b0),
        .LOCKED(locked)
    );

    BUFG bufg_i (
        .I(clk_pll),
        .O(clk_slow)
    );

    reg [21:0] count = 22'd0;
    always @(posedge clk_slow)
        count <= count + 22'd1;

    assign led = count[21] & locked;
endmodule
