// Multiply-accumulate: the DSP48E1 path.
//
// This is the design that guards our own DSP48E1 combinational timing model
// (the one calibrated against Vivado): a regression there shows up as an fmax
// change here, not as a broken bitstream.
module dsp48 (
    input  wire clk,
    output wire led
);
    reg signed [17:0] a = 18'sd3;
    reg signed [17:0] b = 18'sd5;
    reg signed [47:0] acc = 48'sd0;

    always @(posedge clk) begin
        a   <= a + 18'sd1;
        b   <= b + a[3:0];
        acc <= acc + (a * b);
    end

    assign led = ^{acc[47], acc[23], acc[0]};
endmodule
