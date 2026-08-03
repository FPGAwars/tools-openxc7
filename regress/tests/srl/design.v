// A 32-deep rotating shift register with only its last bit observable —
// exactly the shape yosys maps onto a single SRLC32E instead of flip-flops.
// (The `hier` test guards the opposite: there we defeat SRL mapping on
// purpose; here we rely on it.)
//
// Deliberately 32 deep and no deeper: chaining SRLC32Es through the MC31
// cascade has NEVER worked in this toolchain, and that known gap has its
// own expected-fail guard in `srl-cascade`.
module srl (
    input  wire clk,
    output wire led
);
    reg [31:0] sr = 32'h1;

    always @(posedge clk)
        sr <= {sr[30:0], sr[31]};

    assign led = sr[31];
endmodule
