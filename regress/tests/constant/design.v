// A constant driving a pad directly: VCC -> IOB, no logic in between.
//
// The repro of the most valuable bug we have found so far: bbaexport built
// the global VCC/GND node out of column x=0 wires only, so a driver placed
// anywhere else could feed just its own row and `assign led = 1'b1` failed to
// route on EVERY part, with every seed. One line of Verilog, three upstream
// issues closed.
//
// The kept flip-flop only exists so the clock port survives synthesis (the
// generated constraints assign both pads); `led` stays driven by the constant.
module constant (
    input  wire clk,
    output wire led
);
    (* keep *) reg tick = 1'b0;

    always @(posedge clk)
        tick <= ~tick;

    assign led = 1'b1;
endmodule
