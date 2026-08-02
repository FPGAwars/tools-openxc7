// Long carry chain: a 64-bit counter plus a 64-bit adder feeding it.
//
// Exercises the CARRY4 chains and their placement into vertical slices, which
// is where nextpnr's placer and the carry-specific fasm features get stressed.
// The whole state is folded into `led` so nothing can be optimised away.
module carry64 (
    input  wire clk,
    output wire led
);
    reg [63:0] cnt = 64'd0;
    reg [63:0] acc = 64'd0;

    always @(posedge clk) begin
        cnt <= cnt + 64'd1;
        acc <= acc + {cnt[31:0], 32'd1};
    end

    assign led = ^{cnt[63], acc[63], acc[31], cnt[47]};
endmodule
