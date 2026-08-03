// A 128-deep shift register: forces four SRLC32Es chained through the MC31
// cascade. This is EXPECTED TO FAIL — see test.json (status: fail) and the
// README. The day it routes, the expected-fail guard trips and the fix
// must be acknowledged.
module srl_cascade (
    input  wire clk,
    output wire led
);
    reg [127:0] sr = 128'h1;

    always @(posedge clk)
        sr <= {sr[126:0], sr[127]};

    assign led = sr[127];
endmodule
