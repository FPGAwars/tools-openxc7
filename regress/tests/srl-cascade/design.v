// A DEPTH-deep rotating shift register. Anything deeper than 32 forces
// SRLC32Es chained through the dedicated MC31 cascade, which only exists
// inside a SLICEM (D->C->B->A): the packer must cluster each run of four
// into one slice, and chains beyond 128 additionally need the slice-to-
// slice hop moved from Q31 onto Q with the read address tied to 31.
// The rotation feedback keeps `led` live so synthesis cannot trim the
// chain.
module srl_cascade #(
    parameter DEPTH = 128
) (
    input  wire clk,
    output wire led
);
    reg [DEPTH-1:0] sr = {{(DEPTH-1){1'b0}}, 1'b1};

    always @(posedge clk)
        sr <= {sr[DEPTH-2:0], sr[DEPTH-1]};

    assign led = sr[DEPTH-1];
endmodule
