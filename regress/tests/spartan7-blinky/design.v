// Counter blinky for the spartan7 leg of the manifest (Arty S7-50 part).
// spartan7 has no simple upstream demo (the S7 demos are DDR3/litex), so
// this is our own minimal FF+carry+IO design for that family.
module spartan7_blinky (
    input  wire clk,
    output wire led
);
    reg [23:0] count = 0;

    always @(posedge clk)
        count <= count + 1;

    assign led = count[23];
endmodule
