// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: Apache-2.0
//
// FPGA stand-ins for the two IHP memory blocks (256 x 32 and 512 x 32), with
// the same ports, so that src/project.sv builds unchanged on the PYNQ-Z2.
// Each becomes one block RAM with byte write enables.
//
// Behaviour, as the IHP model (test/ihp_sram/) for the way the chip uses the
// blocks: a write stores the bytes whose mask bits are set; a read puts the
// word on A_DOUT after the clock edge and holds it until the next read. The
// chip never reads and writes a block on the same clock, so the IHP model's
// read-during-write result is not reproduced. The mask is used per byte, as
// the chip only ever writes whole bytes. The BIST and A_DLY ports are
// ignored, as on the chip.

`default_nettype none

module fpga_ram #(
    parameter integer AW = 8
) (
    input  wire          clk,
    input  wire          men,
    input  wire          wen,
    input  wire          ren,
    input  wire [AW-1:0] addr,
    input  wire [31:0]   din,
    input  wire [31:0]   bm,
    output reg  [31:0]   dout
);
  (* ram_style = "block" *) reg [31:0] mem [0:(1 << AW) - 1];
  integer i;

  always @(posedge clk) begin
    if (men && wen) begin
      for (i = 0; i < 4; i = i + 1)
        if (|bm[i*8 +: 8]) mem[addr][i*8 +: 8] <= din[i*8 +: 8];
    end
    if (men && ren && !wen) dout <= mem[addr];
  end
endmodule

module RM_IHPSG13_1P_256x32_c2_bm_bist (
    input  wire        A_CLK,
    input  wire        A_MEN,
    input  wire        A_WEN,
    input  wire        A_REN,
    input  wire [7:0]  A_ADDR,
    input  wire [31:0] A_DIN,
    input  wire        A_DLY,
    output wire [31:0] A_DOUT,
    input  wire [31:0] A_BM,
    input  wire        A_BIST_CLK,
    input  wire        A_BIST_EN,
    input  wire        A_BIST_MEN,
    input  wire        A_BIST_WEN,
    input  wire        A_BIST_REN,
    input  wire [7:0]  A_BIST_ADDR,
    input  wire [31:0] A_BIST_DIN,
    input  wire [31:0] A_BIST_BM
);
  fpga_ram #(.AW(8)) u_ram (
      .clk(A_CLK), .men(A_MEN), .wen(A_WEN), .ren(A_REN), .addr(A_ADDR),
      .din(A_DIN), .bm(A_BM), .dout(A_DOUT)
  );
endmodule

module RM_IHPSG13_1P_512x32_c2_bm_bist (
    input  wire        A_CLK,
    input  wire        A_MEN,
    input  wire        A_WEN,
    input  wire        A_REN,
    input  wire [8:0]  A_ADDR,
    input  wire [31:0] A_DIN,
    input  wire        A_DLY,
    output wire [31:0] A_DOUT,
    input  wire [31:0] A_BM,
    input  wire        A_BIST_CLK,
    input  wire        A_BIST_EN,
    input  wire        A_BIST_MEN,
    input  wire        A_BIST_WEN,
    input  wire        A_BIST_REN,
    input  wire [8:0]  A_BIST_ADDR,
    input  wire [31:0] A_BIST_DIN,
    input  wire [31:0] A_BIST_BM
);
  fpga_ram #(.AW(9)) u_ram (
      .clk(A_CLK), .men(A_MEN), .wen(A_WEN), .ren(A_REN), .addr(A_ADDR),
      .din(A_DIN), .bm(A_BM), .dout(A_DOUT)
  );
endmodule

`default_nettype wire
