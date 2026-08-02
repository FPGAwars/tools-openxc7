// Hierarchy that is NOT flattened: submodule port passthroughs.
//
// Regression guard with a history: synth_xilinx does not flatten by default,
// and every test we had was flat, so a frontend bug in merge_nets() went
// unnoticed until a user hit it (the first merge_nets() of a multi-module
// design died with std::out_of_range). Size was never the issue — the missing
// coverage was a structural property.
module hier (
    input  wire clk,
    output wire led
);
    wire a, b;

    stage #(.WIDTH(12)) first  (.clk(clk), .seed(1'b1), .out(a));
    stage #(.WIDTH(10)) second (.clk(clk), .seed(a),    .out(b));

    assign led = a ^ b;
endmodule

module stage #(
    parameter WIDTH = 8
) (
    input  wire clk,
    input  wire seed,
    output wire out
);
    reg [WIDTH-1:0] shifter = {WIDTH{1'b0}};

    always @(posedge clk)
        shifter <= {shifter[WIDTH-2:0], seed ^ shifter[WIDTH-1]};

    // Reduce the WHOLE register, not just its last bit: with only the last bit
    // observable yosys maps this to an SRL, which leaves no flip-flops and no
    // register-to-register path, so the design would carry no timing signal.
    assign out = ^shifter;
endmodule
