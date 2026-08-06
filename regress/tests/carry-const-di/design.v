// Candidato B: CARRY4 explícito con DI=GND y CO con doble fanout
module carry_const_di (input wire clk, output wire led);
    reg [3:0] s_in;
    always @(posedge clk) s_in <= s_in + 1;
    wire [3:0] co, o;
    CARRY4 c0 (.CI(1'b0), .CYINIT(1'b1), .DI(4'b0000), .S(s_in), .CO(co), .O(o));
    reg r1, r2, r3;
    always @(posedge clk) begin r1 <= co[1]; r2 <= co[1] ^ s_in[0]; r3 <= co[3]; end
    wire [7:0] q;
    RAM64X1D #(.INIT(64'h1)) extra_gnd (
        .WCLK(clk), .WE(1'b0), .D(1'b0),
        .A0(s_in[0]), .A1(1'b0), .A2(1'b0), .A3(1'b0), .A4(1'b0), .A5(1'b0),
        .DPRA0(s_in[1]), .DPRA1(1'b0), .DPRA2(1'b0), .DPRA3(1'b0), .DPRA4(1'b0), .DPRA5(1'b0),
        .SPO(q[0]), .DPO(q[1]));
    assign led = r1 ^ r2 ^ r3 ^ q[0] ^ q[1];
endmodule
