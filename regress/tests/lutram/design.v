// Distributed RAM: 64x8 with a synchronous write and an asynchronous read
// (registered afterwards). The ram_style attribute forces the inference to
// LUTRAM so a yosys heuristic change cannot silently turn this into the
// bram test.
module lutram (
    input  wire clk,
    output wire led
);
    (* ram_style = "distributed" *)
    reg [7:0] mem [0:63];

    reg [5:0] wa = 6'd0;
    reg [5:0] ra = 6'd0;
    reg [7:0] wd = 8'h5a;
    reg [7:0] q  = 8'd0;

    always @(posedge clk) begin
        wa <= wa + 6'd1;
        ra <= ra + 6'd3;
        wd <= {wd[6:0], wd[7] ^ wd[3]};
        mem[wa] <= wd;
        q <= mem[ra];
    end

    assign led = ^q;
endmodule
