// Block RAM inference: a 1024 x 16 memory with a registered read port.
//
// Exercises RAMB primitives end to end — inference in yosys, placement and
// routing of the block, and the (large) set of fasm features a BRAM emits.
module bram (
    input  wire clk,
    output wire led
);
    reg [15:0] mem [0:1023];
    reg [9:0]  addr = 10'd0;
    reg [15:0] rdata = 16'd0;
    reg [15:0] wdata = 16'h1234;

    always @(posedge clk) begin
        addr    <= addr + 10'd1;
        wdata   <= {wdata[14:0], wdata[15] ^ wdata[13]};
        mem[addr] <= wdata;
        rdata   <= mem[addr];
    end

    assign led = ^rdata;
endmodule
