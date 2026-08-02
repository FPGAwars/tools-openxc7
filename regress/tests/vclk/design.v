// Plain counter, used with a virtual clock in the constraints.
//
// The design is deliberately boring: what is under test is the XDC path, not
// the logic (see test.json).
module vclk (
    input  wire clk,
    output wire led
);
    reg [23:0] count = 24'd0;

    always @(posedge clk)
        count <= count + 24'd1;

    assign led = count[23];
endmodule
