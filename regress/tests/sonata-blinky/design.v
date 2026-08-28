// Knight-rider blinky for the lowRISC Sonata (Sonata ONE), xc7a50tcsg324.
//
// One lit LED sweeps back and forth across the eight user LEDs, one step
// every ~168 ms (a full round trip takes ~2.3 s).  Board clock is the
// 25 MHz oscillator on pad P15 (`mainClk` in lowRISC's data/pins_sonata.xdc).
module blinky_sonata (
    input  wire       mainClk,          // 25 MHz board oscillator (pad P15)
    output wire [7:0] usrLed            // user LEDs 0..7
);
    reg [21:0] prescaler = 22'd0;       // 2^22 / 25 MHz = 168 ms per step
    reg  [7:0] pattern   = 8'b0000_0001;
    reg        rightward = 1'b0;

    always @(posedge mainClk) begin
        prescaler <= prescaler + 1'b1;
        if (prescaler == 22'd0) begin
            if (rightward) begin
                pattern <= {1'b0, pattern[7:1]};
                if (pattern[1]) rightward <= 1'b0;
            end else begin
                pattern <= {pattern[6:0], 1'b0};
                if (pattern[6]) rightward <= 1'b1;
            end
        end
    end

    assign usrLed = pattern;
endmodule
