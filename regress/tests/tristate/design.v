// A high-Z assignment on the output pad: yosys infers a tristate buffer
// (OBUFT) on the IOB, the only test that configures that side of the pad.
module tristate (
    input  wire clk,
    output wire led
);
    reg [23:0] count = 24'd0;
    always @(posedge clk)
        count <= count + 24'd1;

    wire oe = count[22];
    wire d  = count[23];

    assign led = oe ? d : 1'bz;
endmodule
