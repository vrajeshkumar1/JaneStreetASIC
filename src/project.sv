// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// Top level of the protocol emulator (docs/spec.md).
//
//   pe_pins   input synchronizers, host-link pin borrowing, pin sharing
//   pe_spi    host link (SPI target) -> byte bus
//   pe_regs   host registers and address decoder
//   pe_engine one protocol engine, NE of them
//   u_mem0..3 one IHP memory block per engine, holding its program (and any
//             data the program keeps there): 256 x 32, and 512 x 32 for
//             engine 2
//
// Everything runs on the one clock. Reset is asserted asynchronously and
// released synchronously.
//
// The memory blocks are written out one by one instead of in a loop so that
// each has a plain instance name (u_mem0 .. u_mem3); src/config.json places
// them and connects their power by those names.

`default_nettype none

module tt_um_vrajeshkumar1_janestreetasic (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  localparam int unsigned NE = 4;   // engines. The memory blocks below and
                                    // src/config.json assume four.

  // The engines are not all the same size (docs/spec.md, section 1.1):
  //   engines 0, 1  256-word program, 8-byte FIFOs, 4-byte data memory
  //   engine 2      512-word program, 8-byte FIFOs, 4-byte data memory
  //   engine 3      256-word program, 16-byte FIFOs, 16-byte data memory
  // These are the base-2 logarithms; the generate loop below picks per engine.
  localparam int unsigned AW_BIG   = 9;   // engine 2
  localparam int unsigned AW_STD   = 8;
  localparam int unsigned FIFO_BIG = 4;   // engine 3
  localparam int unsigned FIFO_STD = 3;
  localparam int unsigned DM_BIG   = 4;   // engine 3
  localparam int unsigned DM_STD   = 2;

  // Units an engine may be built without (docs/spec.md, section 1.1). Bit e
  // is engine e.
  localparam logic [3:0] CRC_ENGINES    = 4'b1100;  // checksum unit
  localparam logic [3:0] BSHIFT_ENGINES = 4'b1100;  // shl / shr by 0..15 places
  localparam bit         HOST_RB        = 1'b0;     // 1 = the host can read r0..r7 and the data memory

  // ---------------------------------------------------------------- reset
  logic rst_meta_q, rst_sync_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rst_meta_q <= 1'b0;
      rst_sync_q <= 1'b0;
    end else begin
      rst_meta_q <= 1'b1;
      rst_sync_q <= rst_meta_q;
    end
  end
  wire rst_ni = rst_sync_q;

  // ----------------------------------------------------------------- pins
  wire        host_active, sck, mosi, miso;
  wire        attn_en, attn, lock;
  wire [15:0] owner_out, owner_io;
  wire [7:0]  drive_out, drive_io, open_drain;
  wire [15:0] pins;
  wire [NE*16-1:0] eng_level;
  wire [NE*8-1:0]  eng_dir;

  pe_pins #(.NE(NE)) u_pins (
      .clk          (clk),
      .rst_ni       (rst_ni),
      .ui_in        (ui_in),
      .uo_out       (uo_out),
      .uio_in       (uio_in),
      .uio_out      (uio_out),
      .uio_oe       (uio_oe),
      .lock_i       (lock),
      .host_active_o(host_active),
      .sck_o        (sck),
      .mosi_o       (mosi),
      .miso_i       (miso),
      .attn_en_i    (attn_en),
      .attn_i       (attn),
      .owner_out_i  (owner_out),
      .owner_io_i   (owner_io),
      .drive_out_i  (drive_out),
      .drive_io_i   (drive_io),
      .open_drain_i (open_drain),
      .pins_o       (pins),
      .level_i      (eng_level),
      .dir_i        (eng_dir)
  );

  // ------------------------------------------------------------ host link
  wire [14:0] bus_addr;
  wire        bus_we, bus_reading, bus_hold, bus_rd_pop;
  wire [7:0]  bus_wdata, bus_rdata;

  pe_spi u_spi (
      .clk      (clk),
      .rst_ni   (rst_ni),
      .active_i (host_active),
      .sck_i    (sck),
      .mosi_i   (mosi),
      .miso_o   (miso),
      .addr_o   (bus_addr),
      .we_o     (bus_we),
      .wdata_o  (bus_wdata),
      .reading_o(bus_reading),
      .rdata_i  (bus_rdata),
      .hold_i   (bus_hold),
      .rd_pop_o (bus_rd_pop)
  );

  // ------------------------------------------------------------ registers
  wire [NE-1:0]    enable, restart;
  wire [7:0]       flags;
  wire [NE*8-1:0]  eng_flag_set, eng_flag_clr;

  wire [NE*16-1:0] cfg_clkdiv;
  wire [NE-1:0]    cfg_out_dir, cfg_in_dir, cfg_autopull, cfg_autopush, cfg_crc_dir;
  wire [NE*4-1:0]  cfg_pull_thresh, cfg_push_thresh;
  wire [NE*6-1:0]  cfg_side0, cfg_side1, cfg_crc_width;
  wire [NE*32-1:0] cfg_crc_poly;

  wire [NE-1:0]    stalled, halted, illegal;
  wire [NE*2-1:0]  debug, dbg_clr;
  wire [NE*32-1:0] crc;
  wire [NE*9-1:0]  pc;
  wire [NE-1:0]    pc_we;
  wire [8:0]       pc_wdata;
  wire [NE*12-1:0] eng_size;
  wire [NE*2-1:0]  eng_feat;

  wire [NE-1:0]    tx_push, tx_full, tx_empty, rx_pop, rx_empty, rx_full;
  wire [7:0]       tx_data;
  wire [NE*5-1:0]  tx_level, rx_level;
  wire [NE*8-1:0]  rx_data;

  wire [NE-1:0]    dm_we;
  wire [3:0]       dm_addr;
  wire [7:0]       dm_wdata;
  wire [NE*8-1:0]  dm_rdata;

  wire [NE-1:0]    hreg_we;
  wire [2:0]       hreg_sel;
  wire             hreg_hi;
  wire [7:0]       hreg_wdata;
  wire [NE*16-1:0] hreg_rdata;

  wire [NE-1:0]    prog_we, prog_re;
  wire [8:0]       prog_addr;
  wire [31:0]      prog_wdata;
  wire [NE*32-1:0] mem_dout;

  // A flag is set or cleared if any engine asks for it.
  logic [7:0] flag_set_any, flag_clr_any;
  integer     k;
  always_comb begin
    flag_set_any = 8'h00;
    flag_clr_any = 8'h00;
    for (k = 0; k < NE; k = k + 1) begin
      flag_set_any = flag_set_any | eng_flag_set[k*8 +: 8];
      flag_clr_any = flag_clr_any | eng_flag_clr[k*8 +: 8];
    end
  end

  pe_regs #(.NE(NE), .HAS_CRC(CRC_ENGINES), .HOST_RB(HOST_RB)) u_regs (
      .clk              (clk),
      .rst_ni           (rst_ni),
      .addr_i           (bus_addr),
      .we_i             (bus_we),
      .wdata_i          (bus_wdata),
      .reading_i        (bus_reading),
      .rdata_o          (bus_rdata),
      .hold_o           (bus_hold),
      .rd_pop_i         (bus_rd_pop),
      .enable_o         (enable),
      .restart_o        (restart),
      .flags_o          (flags),
      .flag_set_i       (flag_set_any),
      .flag_clr_i       (flag_clr_any),
      .owner_out_o      (owner_out),
      .owner_io_o       (owner_io),
      .drive_out_o      (drive_out),
      .drive_io_o       (drive_io),
      .open_drain_o     (open_drain),
      .attn_en_o        (attn_en),
      .attn_o           (attn),
      .lock_o           (lock),
      .cfg_clkdiv_o     (cfg_clkdiv),
      .cfg_out_dir_o    (cfg_out_dir),
      .cfg_in_dir_o     (cfg_in_dir),
      .cfg_autopull_o   (cfg_autopull),
      .cfg_autopush_o   (cfg_autopush),
      .cfg_pull_thresh_o(cfg_pull_thresh),
      .cfg_push_thresh_o(cfg_push_thresh),
      .cfg_side0_o      (cfg_side0),
      .cfg_side1_o      (cfg_side1),
      .cfg_crc_dir_o    (cfg_crc_dir),
      .cfg_crc_poly_o   (cfg_crc_poly),
      .cfg_crc_width_o  (cfg_crc_width),
      .stalled_i        (stalled),
      .halted_i         (halted),
      .illegal_i        (illegal),
      .debug_i          (debug),
      .dbg_clr_o        (dbg_clr),
      .crc_i            (crc),
      .pc_i             (pc),
      .pc_we_o          (pc_we),
      .pc_wdata_o       (pc_wdata),
      .size_i           (eng_size),
      .feat_i           (eng_feat),
      .tx_push_o        (tx_push),
      .tx_data_o        (tx_data),
      .tx_full_i        (tx_full),
      .tx_empty_i       (tx_empty),
      .tx_level_i       (tx_level),
      .rx_pop_o         (rx_pop),
      .rx_data_i        (rx_data),
      .rx_empty_i       (rx_empty),
      .rx_full_i        (rx_full),
      .rx_level_i       (rx_level),
      .dm_we_o          (dm_we),
      .dm_addr_o        (dm_addr),
      .dm_wdata_o       (dm_wdata),
      .dm_rdata_i       (dm_rdata),
      .hreg_we_o        (hreg_we),
      .hreg_sel_o       (hreg_sel),
      .hreg_hi_o        (hreg_hi),
      .hreg_wdata_o     (hreg_wdata),
      .hreg_rdata_i     (hreg_rdata),
      .prog_we_o        (prog_we),
      .prog_re_o        (prog_re),
      .prog_addr_o      (prog_addr),
      .prog_wdata_o     (prog_wdata),
      .prog_rdata_i     (mem_dout)
  );

  // -------------------------------------------------------------- engines
  // Memory-block signals are nine address bits wide for every engine; an
  // engine with a 256-word block leaves the top bit at zero.
  wire [NE-1:0]    eng_ren, eng_wen;
  wire [NE*9-1:0]  eng_addr;
  wire [NE*32-1:0] eng_din, eng_bm;

  genvar g;
  generate
    for (g = 0; g < NE; g = g + 1) begin : g_eng
      localparam int unsigned AW_G   = (g == 2) ? AW_BIG   : AW_STD;
      localparam int unsigned FIFO_G = (g == 3) ? FIFO_BIG : FIFO_STD;
      localparam int unsigned DM_G   = (g == 3) ? DM_BIG   : DM_STD;
      localparam bit          CRC_G  = CRC_ENGINES[g];
      localparam bit          BSH_G  = BSHIFT_ENGINES[g];

      wire [AW_G-1:0] e_addr, e_pc;

      // Zero-extend to nine bits.
      logic [8:0] addr9, pc9;
      always_comb begin
        addr9 = '0;
        pc9   = '0;
        addr9[AW_G-1:0] = e_addr;
        pc9[AW_G-1:0]   = e_pc;
      end
      assign eng_addr[g*9 +: 9]   = addr9;
      assign pc[g*9 +: 9]         = pc9;
      assign eng_size[g*12 +: 12] = {DM_G[3:0], FIFO_G[3:0], AW_G[3:0]};
      assign eng_feat[g*2 +: 2]   = {BSH_G, CRC_G};

      pe_engine #(.AW(AW_G), .FIFO_AW(FIFO_G), .DM_AW(DM_G),
                  .HAS_CRC(CRC_G), .HAS_BSHIFT(BSH_G), .HOST_RB(HOST_RB)) u_engine (
          .clk              (clk),
          .rst_ni           (rst_ni),
          .enable_i         (enable[g]),
          .restart_i        (restart[g]),
          .cfg_clkdiv_i     (cfg_clkdiv[g*16 +: 16]),
          .cfg_out_dir_i    (cfg_out_dir[g]),
          .cfg_in_dir_i     (cfg_in_dir[g]),
          .cfg_autopull_i   (cfg_autopull[g]),
          .cfg_autopush_i   (cfg_autopush[g]),
          .cfg_pull_thresh_i(cfg_pull_thresh[g*4 +: 4]),
          .cfg_push_thresh_i(cfg_push_thresh[g*4 +: 4]),
          .cfg_side0_i      (cfg_side0[g*6 +: 6]),
          .cfg_side1_i      (cfg_side1[g*6 +: 6]),
          .cfg_crc_dir_i    (cfg_crc_dir[g]),
          .cfg_crc_poly_i   (cfg_crc_poly[g*32 +: 32]),
          .cfg_crc_width_i  (cfg_crc_width[g*6 +: 6]),
          .pins_i           (pins),
          .pin_level_o      (eng_level[g*16 +: 16]),
          .pin_dir_o        (eng_dir[g*8 +: 8]),
          .flags_i          (flags),
          .flag_set_o       (eng_flag_set[g*8 +: 8]),
          .flag_clr_o       (eng_flag_clr[g*8 +: 8]),
          .mem_ren_o        (eng_ren[g]),
          .mem_addr_o       (e_addr),
          .mem_wen_o        (eng_wen[g]),
          .mem_din_o        (eng_din[g*32 +: 32]),
          .mem_bm_o         (eng_bm[g*32 +: 32]),
          .mem_dout_i       (mem_dout[g*32 +: 32]),
          .tx_push_i        (tx_push[g]),
          .tx_data_i        (tx_data),
          .tx_full_o        (tx_full[g]),
          .tx_empty_o       (tx_empty[g]),
          .tx_level_o       (tx_level[g*5 +: 5]),
          .rx_pop_i         (rx_pop[g]),
          .rx_data_o        (rx_data[g*8 +: 8]),
          .rx_empty_o       (rx_empty[g]),
          .rx_full_o        (rx_full[g]),
          .rx_level_o       (rx_level[g*5 +: 5]),
          .dm_we_i          (dm_we[g]),
          .dm_addr_i        (dm_addr),
          .dm_wdata_i       (dm_wdata),
          .dm_rdata_o       (dm_rdata[g*8 +: 8]),
          .hreg_we_i        (hreg_we[g]),
          .hreg_sel_i       (hreg_sel),
          .hreg_hi_i        (hreg_hi),
      .hreg_wdata_i     (hreg_wdata),
          .hreg_rdata_o     (hreg_rdata[g*16 +: 16]),
          .pc_we_i          (pc_we[g]),
          .pc_wdata_i       (pc_wdata[AW_G-1:0]),
          .pc_o             (e_pc),
          .stalled_o        (stalled[g]),
          .halted_o         (halted[g]),
          .illegal_o        (illegal[g]),
          .debug_o          (debug[g*2 +: 2]),
          .dbg_clr_i        (dbg_clr[g*2 +: 2]),
          .crc_o            (crc[g*32 +: 32])
      );
    end
  endgenerate

  // ------------------------------------------------------ program memory
  // While an engine is enabled its memory block follows the engine, which
  // fetches instructions and can load and store data bytes (ldm / stm). While
  // it is stopped the block follows the host, which can then write and read
  // it. The engine only asks when enabled and pe_regs only when it is not, so
  // the two never ask on the same clock.
  wire [NE-1:0]    mem_wen  = eng_wen | prog_we;
  wire [NE-1:0]    mem_ren  = eng_ren | prog_re;
  wire [NE-1:0]    mem_men  = mem_wen | mem_ren;
  wire [NE*9-1:0]  mem_addr;
  wire [NE*32-1:0] mem_din, mem_bm;

  generate
    for (g = 0; g < NE; g = g + 1) begin : g_mmux
      assign mem_addr[g*9 +: 9]  = enable[g] ? eng_addr[g*9 +: 9] : prog_addr;
      assign mem_din[g*32 +: 32] = enable[g] ? eng_din[g*32 +: 32] : prog_wdata;
      assign mem_bm[g*32 +: 32]  = enable[g] ? eng_bm[g*32 +: 32]  : 32'hFFFF_FFFF;
    end
  endgenerate

  RM_IHPSG13_1P_256x32_c2_bm_bist u_mem0 (
      .A_CLK      (clk),
      .A_MEN      (mem_men[0]),
      .A_WEN      (mem_wen[0]),
      .A_REN      (mem_ren[0]),
      .A_ADDR     (mem_addr[0*9 +: 8]),
      .A_DIN      (mem_din[0*32 +: 32]),
      .A_DLY      (1'b1),
      .A_DOUT     (mem_dout[0*32 +: 32]),
      .A_BM       (mem_bm[0*32 +: 32]),
      .A_BIST_CLK (1'b0),
      .A_BIST_EN  (1'b0),
      .A_BIST_MEN (1'b0),
      .A_BIST_WEN (1'b0),
      .A_BIST_REN (1'b0),
      .A_BIST_ADDR(8'h0),
      .A_BIST_DIN (32'h0000_0000),
      .A_BIST_BM  (32'h0000_0000)
  );

  RM_IHPSG13_1P_256x32_c2_bm_bist u_mem1 (
      .A_CLK      (clk),
      .A_MEN      (mem_men[1]),
      .A_WEN      (mem_wen[1]),
      .A_REN      (mem_ren[1]),
      .A_ADDR     (mem_addr[1*9 +: 8]),
      .A_DIN      (mem_din[1*32 +: 32]),
      .A_DLY      (1'b1),
      .A_DOUT     (mem_dout[1*32 +: 32]),
      .A_BM       (mem_bm[1*32 +: 32]),
      .A_BIST_CLK (1'b0),
      .A_BIST_EN  (1'b0),
      .A_BIST_MEN (1'b0),
      .A_BIST_WEN (1'b0),
      .A_BIST_REN (1'b0),
      .A_BIST_ADDR(8'h0),
      .A_BIST_DIN (32'h0000_0000),
      .A_BIST_BM  (32'h0000_0000)
  );

  RM_IHPSG13_1P_512x32_c2_bm_bist u_mem2 (
      .A_CLK      (clk),
      .A_MEN      (mem_men[2]),
      .A_WEN      (mem_wen[2]),
      .A_REN      (mem_ren[2]),
      .A_ADDR     (mem_addr[2*9 +: 9]),
      .A_DIN      (mem_din[2*32 +: 32]),
      .A_DLY      (1'b1),
      .A_DOUT     (mem_dout[2*32 +: 32]),
      .A_BM       (mem_bm[2*32 +: 32]),
      .A_BIST_CLK (1'b0),
      .A_BIST_EN  (1'b0),
      .A_BIST_MEN (1'b0),
      .A_BIST_WEN (1'b0),
      .A_BIST_REN (1'b0),
      .A_BIST_ADDR(9'h0),
      .A_BIST_DIN (32'h0000_0000),
      .A_BIST_BM  (32'h0000_0000)
  );

  RM_IHPSG13_1P_256x32_c2_bm_bist u_mem3 (
      .A_CLK      (clk),
      .A_MEN      (mem_men[3]),
      .A_WEN      (mem_wen[3]),
      .A_REN      (mem_ren[3]),
      .A_ADDR     (mem_addr[3*9 +: 8]),
      .A_DIN      (mem_din[3*32 +: 32]),
      .A_DLY      (1'b1),
      .A_DOUT     (mem_dout[3*32 +: 32]),
      .A_BM       (mem_bm[3*32 +: 32]),
      .A_BIST_CLK (1'b0),
      .A_BIST_EN  (1'b0),
      .A_BIST_MEN (1'b0),
      .A_BIST_WEN (1'b0),
      .A_BIST_REN (1'b0),
      .A_BIST_ADDR(8'h0),
      .A_BIST_DIN (32'h0000_0000),
      .A_BIST_BM  (32'h0000_0000)
  );

  // "ena" is not used: the design has nothing to do when it is not selected.
  // and the top address bit of the three 256-word blocks.
  wire _unused = &{ena, mem_addr[0*9 + 8], mem_addr[1*9 + 8], mem_addr[3*9 + 8], 1'b0};

endmodule

`default_nettype wire
