// Parametric congestion bench: N blocks of a W-bit rotate-XOR register.
// Every block reads TWO neighbour buses:
//
//   ring:  block (i+1) mod N          -- keeps the whole design alive and
//                                        observable from block 0
//   far:   block (i*MUL + ADD) mod N  -- pure traffic, the congestion knob
//
// Utilisation is FIXED; only where the far links go changes:
//   MUL=1,  ADD=3  -> far links are also neighbours (the control leg)
//   MUL=61, ADD=7  -> far links scatter across the whole array (stress leg)
//
// The ring alone would not do: (i+STRIDE) mod N is topologically still a
// ring whatever the stride, and a placer may lay any ring out as a snake,
// making it local again. An affine map with MUL far from 1 has high graph
// bandwidth: no placement can make ring AND far links short at once. And a
// purely multiplicative map (i*STRIDE mod N) silently pins block 0 to
// itself (0*S = 0), detaching the rest -- the collapse the FDRE assertion
// caught on this bench's first run.
module congestion #(
    parameter N   = 192,
    parameter W   = 64,
    parameter MUL = 1,
    parameter ADD = 3
) (
    input  wire clk,
    output wire led
);
    wire [N*W-1:0] state;

    genvar i;
    generate
        for (i = 0; i < N; i = i + 1) begin : blk
            localparam integer RING = (i + 1) % N;
            localparam integer FAR  = (i * MUL + ADD) % N;
            // A distinct SEED per block breaks the symmetry: with a common
            // all-zero reset every block's state is provably identical
            // forever (rot(s)^s^s == rot(s) for all of them at once) and
            // opt_merge fuses the N registers into one -- the second
            // collapse the FDRE assertion caught on this bench.
            mixcell #(.W(W), .SEED(32'h9E3779B9 * (i + 1))) m (
                .clk(clk),
                .ring(state[RING*W +: W]),
                .far(state[FAR*W +: W]),
                .out(state[i*W +: W])
            );
        end
    endgenerate

    assign led = ^state[0 +: W];
endmodule

module mixcell #(
    parameter W = 64,
    parameter [31:0] SEED = 32'h1
) (
    input  wire         clk,
    input  wire [W-1:0] ring,
    input  wire [W-1:0] far,
    output wire [W-1:0] out
);
    reg [W-1:0] r = {W/32{SEED}};

    always @(posedge clk)
        r <= {r[W-2:0], ~r[W-1]} ^ ring ^ far;

    assign out = r;
endmodule
