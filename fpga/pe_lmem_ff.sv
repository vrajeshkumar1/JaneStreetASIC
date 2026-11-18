// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: Apache-2.0
//
// FPGA version of pe_lmem (src/pe_fifo.sv): the same storage built from
// flip-flops with a write enable, because an FPGA has no clock-gate cell and
// its tools time latches on gated clocks poorly. Seen from its ports it is
// the same as the latch version: a byte written on one clock edge reads back
// with its new value after that edge, and everything is zero after reset.
// fpga/build.tcl removes pe_clkgate and pe_lmem from a copy of pe_fifo.sv and
// uses this file instead.

`default_nettype none

module pe_lmem #(
    parameter int unsigned AW = 3
) (
    input  wire                  clk,
    input  wire                  rst_ni,
    input  wire                  we_i,
    input  wire [AW-1:0]         waddr_i,
    input  wire [7:0]            wdata_i,
    output wire [(8<<AW)-1:0]    q_o
);
  logic [(8<<AW)-1:0] q;
  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni)   q <= '0;
    else if (we_i) q[waddr_i*8 +: 8] <= wdata_i;
  end
  assign q_o = q;
endmodule

`default_nettype wire
