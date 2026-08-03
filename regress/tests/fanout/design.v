// One flip-flop driving 256 loads: high-fanout distribution, the property
// the congestion pair deliberately does NOT exercise (their traffic is
// point-to-point). Stresses net buffering/replication and the fanout side
// of the timing model.
module fanout (
    input  wire clk,
    output wire led
);
    reg tick = 1'b0;
    reg [255:0] taps = 256'd1;

    always @(posedge clk) begin
        tick <= ~tick;
        taps <= {taps[254:0], ^taps[255:224]} ^ {256{tick}};
    end

    assign led = ^taps;
endmodule
