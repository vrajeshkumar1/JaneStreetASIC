// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// Black-box declarations of the two IHP single-port memory blocks the design
// uses (256 x 32 and 512 x 32), for synthesis only. The blocks are finished
// pieces of layout, so the synthesis tool must not try to build them; it only
// needs the port lists.
// Simulation defines SIM and uses the PDK's behavioural model in
// test/ihp_sram/ instead.
`ifndef SIM
(* blackbox *)
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
endmodule

(* blackbox *)
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
endmodule
`endif
