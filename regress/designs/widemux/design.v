// Wide multiplexer: F7/F8 muxes and fractured LUTs sharing input pins.
//
// This is the shape that once produced false timing loops in the post-route
// pin fixup and emptied the clock table, so it guards both the timing walk
// and the fractured-LUT pin handling.
module widemux (
    input  wire clk,
    output wire led
);
    reg [31:0] r = 32'h0000_0001;
    reg [4:0]  s = 5'd0;
    reg        o = 1'b0;

    always @(posedge clk) begin
        r <= {r[30:0], r[31] ^ r[21] ^ r[1] ^ r[0]};
        s <= s + {4'd0, r[0]};
        o <= r[s];
    end

    assign led = o;
endmodule
