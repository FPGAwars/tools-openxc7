// Minimal part-agnostic design for the multi-part E2E smoke: one clock,
// one LED. The XDC is generated per part from the prjxray-db package pins
// (see gen_xdc.py).
module blinky (
    input  wire clk,
    output wire led
);
    reg [23:0] counter = 0;

    always @(posedge clk)
        counter <= counter + 1;

    assign led = counter[23];
endmodule
