// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// Test bench for one engine. It supplies what the rest of the chip will
// supply: the program memory block, the settings registers, the shared flags,
// the input synchronizers and the pin drivers (including open-drain pins with
// pull-ups). The cocotb tests drive the "h_" signals in place of the
// host interface.

`default_nettype none
`timescale 1ns / 1ps

module tb_engine ();

  initial begin
    $dumpfile("tb_engine.fst");
    $dumpvars(0, tb_engine);
    #1;
  end

  reg clk;
  reg rst_n;

  // ---- control and settings (driven by the tests)
  reg        enable;
  reg        restart;
  reg [15:0] cfg_clkdiv;
  reg        cfg_out_dir, cfg_in_dir, cfg_autopull, cfg_autopush;
  reg [3:0]  cfg_pull_thresh, cfg_push_thresh;
  reg [5:0]  cfg_side0, cfg_side1;
  reg        cfg_crc_dir;
  reg [31:0] cfg_crc_poly;
  reg [5:0]  cfg_crc_width;
  reg [7:0]  cfg_open_drain;     // per bidirectional pin

  // ---- host stand-ins
  reg        h_prog_we;
  reg [7:0]  h_prog_addr;
  reg [31:0] h_prog_wdata;
  reg        h_tx_push;
  reg [7:0]  h_tx_data;
  reg        h_rx_pop;
  reg        h_dm_we;
  reg [3:0]  h_dm_addr;
  reg [7:0]  h_dm_wdata;
  reg        h_reg_we;
  reg [2:0]  h_reg_sel;
  reg        h_reg_hi;
  reg [7:0]  h_reg_wdata;
  reg        h_pc_we;
  reg [7:0]  h_pc_wdata;
  reg [7:0]  h_flag_set, h_flag_clr;

  wire        tx_full, tx_empty, rx_full, rx_empty;
  wire [4:0]  tx_level, rx_level;
  wire [7:0]  rx_data, dm_rdata, pc;
  wire [15:0] reg_rdata;
  wire        stalled, halted, illegal;
  wire [1:0]  debug;
  wire [31:0] crc;

  // ---- pins
  reg  [7:0] ui_in;      // input pins, driven by the tests
  reg  [7:0] io_ext;     // what the outside world puts on each bidirectional
                         // line when the engine is not driving it (1 = pull-up)
  wire [7:0] uo_out;     // output pins
  wire [7:0] io_line;    // resolved level of each bidirectional line

  wire [15:0] pin_level;
  wire [7:0]  pin_dir;

  // Pin drivers as in src/pe_pins.sv: one flip-flop on every output.
  // Open-drain pin: never driven high. Level 1 releases, level 0 pulls low.
  wire [7:0] io_oe_d  = (cfg_open_drain & ~pin_level[15:8]) | (~cfg_open_drain & pin_dir);
  wire [7:0] io_out_d = pin_level[15:8] & ~cfg_open_drain;

  reg [7:0] uo_q, io_oe, io_out;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      uo_q   <= 8'h00;
      io_oe  <= 8'h00;
      io_out <= 8'h00;
    end else begin
      uo_q   <= pin_level[7:0];
      io_oe  <= io_oe_d;
      io_out <= io_out_d;
    end
  end

  genvar g;
  generate
    for (g = 0; g < 8; g = g + 1) begin : g_io
      assign io_line[g] = io_oe[g] ? io_out[g] : io_ext[g];
    end
  endgenerate

  assign uo_out = uo_q;

  // Two flip-flops on every input, as the chip will have.
  reg [15:0] pins_meta, pins_sync;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pins_meta <= 16'hFFFF;
      pins_sync <= 16'hFFFF;
    end else begin
      pins_meta <= {io_line, ui_in};
      pins_sync <= pins_meta;
    end
  end

  // ---- shared flags
  reg  [7:0] flags;
  wire [7:0] flag_set, flag_clr;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) flags <= 8'h00;
    else flags <= (flags & ~(flag_clr | h_flag_clr)) | flag_set | h_flag_set;
  end

  // ---- program memory
  wire        mem_ren;
  wire [7:0]  mem_addr;
  wire [31:0] mem_dout;
  wire        mem_wen;
  wire [31:0] mem_din, mem_bm;

  RM_IHPSG13_1P_256x32_c2_bm_bist u_mem (
      .A_CLK      (clk),
      .A_MEN      (h_prog_we | mem_ren | mem_wen),
      .A_WEN      (h_prog_we | mem_wen),
      .A_REN      (mem_ren & ~h_prog_we),
      .A_ADDR     (h_prog_we ? h_prog_addr : mem_addr),
      .A_DIN      (h_prog_we ? h_prog_wdata : mem_din),
      .A_DLY      (1'b1),
      .A_DOUT     (mem_dout),
      .A_BM       (h_prog_we ? 32'hFFFF_FFFF : mem_bm),
      .A_BIST_CLK (1'b0),
      .A_BIST_EN  (1'b0),
      .A_BIST_MEN (1'b0),
      .A_BIST_WEN (1'b0),
      .A_BIST_REN (1'b0),
      .A_BIST_ADDR(8'h00),
      .A_BIST_DIN (32'h0000_0000),
      .A_BIST_BM  (32'h0000_0000)
  );

  pe_engine #(.AW(8)) dut (
      .clk              (clk),
      .rst_ni           (rst_n),
      .enable_i         (enable),
      .restart_i        (restart),
      .cfg_clkdiv_i     (cfg_clkdiv),
      .cfg_out_dir_i    (cfg_out_dir),
      .cfg_in_dir_i     (cfg_in_dir),
      .cfg_autopull_i   (cfg_autopull),
      .cfg_autopush_i   (cfg_autopush),
      .cfg_pull_thresh_i(cfg_pull_thresh),
      .cfg_push_thresh_i(cfg_push_thresh),
      .cfg_side0_i      (cfg_side0),
      .cfg_side1_i      (cfg_side1),
      .cfg_crc_dir_i    (cfg_crc_dir),
      .cfg_crc_poly_i   (cfg_crc_poly),
      .cfg_crc_width_i  (cfg_crc_width),
      .pins_i           (pins_sync),
      .pin_level_o      (pin_level),
      .pin_dir_o        (pin_dir),
      .flags_i          (flags),
      .flag_set_o       (flag_set),
      .flag_clr_o       (flag_clr),
      .mem_ren_o        (mem_ren),
      .mem_addr_o       (mem_addr),
      .mem_wen_o        (mem_wen),
      .mem_din_o        (mem_din),
      .mem_bm_o         (mem_bm),
      .mem_dout_i       (mem_dout),
      .tx_push_i        (h_tx_push),
      .tx_data_i        (h_tx_data),
      .tx_full_o        (tx_full),
      .tx_empty_o       (tx_empty),
      .tx_level_o       (tx_level),
      .rx_pop_i         (h_rx_pop),
      .rx_data_o        (rx_data),
      .rx_empty_o       (rx_empty),
      .rx_full_o        (rx_full),
      .rx_level_o       (rx_level),
      .dm_we_i          (h_dm_we),
      .dm_addr_i        (h_dm_addr),
      .dm_wdata_i       (h_dm_wdata),
      .dm_rdata_o       (dm_rdata),
      .hreg_we_i        (h_reg_we),
      .hreg_sel_i       (h_reg_sel),
      .hreg_hi_i        (h_reg_hi),
      .hreg_wdata_i     (h_reg_wdata),
      .hreg_rdata_o     (reg_rdata),
      .pc_we_i          (h_pc_we),
      .pc_wdata_i       (h_pc_wdata),
      .pc_o             (pc),
      .stalled_o        (stalled),
      .halted_o         (halted),
      .illegal_o        (illegal),
      .debug_o          (debug),
      .dbg_clr_i        (2'b00),
      .crc_o            (crc)
  );

endmodule

`default_nettype wire
