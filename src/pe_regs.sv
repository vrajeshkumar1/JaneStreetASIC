// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// Host-visible registers and the address decoder (docs/spec.md, sections 2.3
// to 2.5). One side is the byte bus of pe_spi.sv; the other side is the
// settings, controls and status of every engine, the shared flags and the pin
// settings.
//
// Address map (15-bit address):
//   0x0000..0x003F      global registers
//   0x0100 + 0x40 * e   registers of engine e
//   0x0200 + 0x10 * e   data memory of engine e
//   0x4000 + 0x800 * e  program memory of engine e, 4 bytes per word, up to
//                       512 words
//
// The map has room for four engines; NE may be 1 to 4. Per-engine buses are
// flat vectors: engine e uses bits [e*W +: W] of a bus whose entries are W
// bits wide.
//
// Naming: *_q is a flip-flop output, *_i / *_o are ports.

`default_nettype none

module pe_regs #(
    parameter int unsigned NE = 4,         // number of engines, 1..4
    parameter logic [3:0]  HAS_CRC = 4'b1111,   // bit e: engine e has a checksum unit
    parameter bit          HOST_RB = 1'b1       // 0 = r0..r7 and the data memory read as zero
) (
    input  wire            clk,
    input  wire            rst_ni,

    // ---- byte bus (pe_spi.sv)
    input  wire [14:0]     addr_i,
    input  wire            we_i,
    input  wire [7:0]      wdata_i,
    input  wire            reading_i,
    output logic [7:0]     rdata_o,
    output wire            hold_o,
    input  wire            rd_pop_i,

    // ---- engine control
    output wire [NE-1:0]   enable_o,
    output wire [NE-1:0]   restart_o,

    // ---- shared flags
    output wire [7:0]      flags_o,
    input  wire [7:0]      flag_set_i,     // from the engines
    input  wire [7:0]      flag_clr_i,

    // ---- pin settings
    output wire [15:0]     owner_out_o,    // two bits per output pin
    output wire [15:0]     owner_io_o,     // two bits per bidirectional pin
    output wire [7:0]      drive_out_o,
    output wire [7:0]      drive_io_o,
    output wire [7:0]      open_drain_o,
    output wire            attn_en_o,      // out0 is the attention line
    output wire            attn_o,
    output wire            lock_o,         // ignore host select until reset

    // ---- engine settings
    output wire [NE*16-1:0] cfg_clkdiv_o,
    output wire [NE-1:0]    cfg_out_dir_o,
    output wire [NE-1:0]    cfg_in_dir_o,
    output wire [NE-1:0]    cfg_autopull_o,
    output wire [NE-1:0]    cfg_autopush_o,
    output wire [NE*4-1:0]  cfg_pull_thresh_o,
    output wire [NE*4-1:0]  cfg_push_thresh_o,
    output wire [NE*6-1:0]  cfg_side0_o,
    output wire [NE*6-1:0]  cfg_side1_o,
    output wire [NE-1:0]    cfg_crc_dir_o,
    output wire [NE*32-1:0] cfg_crc_poly_o,
    output wire [NE*6-1:0]  cfg_crc_width_o,

    // ---- engine status
    input  wire [NE-1:0]    stalled_i,
    input  wire [NE-1:0]    halted_i,
    input  wire [NE-1:0]    illegal_i,
    input  wire [NE*2-1:0]  debug_i,
    output wire [NE*2-1:0]  dbg_clr_o,
    input  wire [NE*32-1:0] crc_i,

    // ---- program counter
    input  wire [NE*9-1:0]  pc_i,           // nine bits per engine, zero-padded
    output wire [NE-1:0]    pc_we_o,
    output wire [8:0]       pc_wdata_o,

    // ---- sizes of each engine, constants: [3:0] log2 of program words,
    //      [7:4] log2 of FIFO bytes, [11:8] log2 of data memory bytes
    input  wire [NE*12-1:0] size_i,
    input  wire [NE*2-1:0]  feat_i,         // [0] checksum unit, [1] 16-place shifter

    // ---- FIFOs
    output wire [NE-1:0]    tx_push_o,
    output wire [7:0]       tx_data_o,
    input  wire [NE-1:0]    tx_full_i,
    input  wire [NE-1:0]    tx_empty_i,
    input  wire [NE*5-1:0]  tx_level_i,
    output wire [NE-1:0]    rx_pop_o,
    input  wire [NE*8-1:0]  rx_data_i,
    input  wire [NE-1:0]    rx_empty_i,
    input  wire [NE-1:0]    rx_full_i,
    input  wire [NE*5-1:0]  rx_level_i,

    // ---- data memory
    output wire [NE-1:0]    dm_we_o,
    output wire [3:0]       dm_addr_o,
    output wire [7:0]       dm_wdata_o,
    input  wire [NE*8-1:0]  dm_rdata_i,

    // ---- registers r0..r7
    output wire [NE-1:0]    hreg_we_o,
    output wire [2:0]       hreg_sel_o,
    output wire             hreg_hi_o,
    output wire [7:0]       hreg_wdata_o,
    input  wire [NE*16-1:0] hreg_rdata_i,

    // ---- program memory
    output wire [NE-1:0]    prog_we_o,
    output wire [NE-1:0]    prog_re_o,
    output wire [8:0]       prog_addr_o,
    output wire [31:0]      prog_wdata_o,
    input  wire [NE*32-1:0] prog_rdata_i
);

  localparam logic [7:0] ID_VALUE      = 8'h4A;
  localparam logic [7:0] VERSION_VALUE = 8'h01;

  // ------------------------------------------------------- address decode
  wire sel_glob = (addr_i[14:6]  == 9'h000);   // 0x0000..0x003F
  wire sel_ereg = (addr_i[14:8]  == 7'h01);    // 0x0100..0x01FF
  wire sel_dmem = (addr_i[14:6]  == 9'h008);   // 0x0200..0x023F
  wire sel_prog = (addr_i[14:13] == 2'b10);    // 0x4000..0x5FFF

  wire [5:0] off = addr_i[5:0];                // offset inside a block

  // The engine number sits in a different place in each block.
  logic [1:0] e;
  always_comb begin
    if (sel_ereg)      e = addr_i[7:6];
    else if (sel_dmem) e = addr_i[5:4];
    else               e = addr_i[12:11];
  end

  // One-hot engine select; all zero when the address names an engine that
  // does not exist.
  logic [NE-1:0] e_hot;
  integer        i;
  always_comb begin
    e_hot = '0;
    for (i = 0; i < NE; i = i + 1) begin
      if (e == i[1:0]) e_hot[i] = 1'b1;
    end
  end

  assign hold_o = sel_ereg & (off == 6'h0C);

  // ----------------------------------------------------- global registers
  logic [NE-1:0] enable_q, restart_q;
  logic [7:0]    flags_q, attn_mask_q;
  logic          attn_en_q, lock_q;
  logic [15:0]   owner_out_q, owner_io_q;
  logic [7:0]    drive_out_q, drive_io_q, open_drain_q;

  wire we_glob = we_i & sel_glob;

  wire [7:0] host_flag_set = (we_glob && off == 6'h05) ? wdata_i : 8'h00;
  wire [7:0] host_flag_clr = (we_glob && off == 6'h06) ? wdata_i : 8'h00;

  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      enable_q     <= '0;
      restart_q    <= '0;
      flags_q      <= '0;
      attn_mask_q  <= '0;
      attn_en_q    <= 1'b0;
      lock_q       <= 1'b0;
      owner_out_q  <= '0;
      owner_io_q   <= '0;
      drive_out_q  <= '0;
      drive_io_q   <= '0;
      open_drain_q <= '0;
    end else begin
      restart_q <= '0;                          // RESTART is a one-clock pulse
      flags_q   <= (flags_q & ~(flag_clr_i | host_flag_clr)) | flag_set_i | host_flag_set;
      if (we_glob) begin
        case (off)
          6'h02: enable_q           <= wdata_i[NE-1:0];
          6'h03: restart_q          <= wdata_i[NE-1:0];
          6'h07: attn_mask_q        <= wdata_i;
          6'h08: begin
            attn_en_q <= wdata_i[0];
            lock_q    <= lock_q | wdata_i[1];   // only a reset clears the lock
          end
          6'h10: owner_out_q[7:0]   <= wdata_i;
          6'h11: owner_out_q[15:8]  <= wdata_i;
          6'h12: owner_io_q[7:0]    <= wdata_i;
          6'h13: owner_io_q[15:8]   <= wdata_i;
          6'h14: drive_out_q        <= wdata_i;
          6'h15: drive_io_q         <= wdata_i;
          6'h16: open_drain_q       <= wdata_i;
          default: ;
        endcase
      end
    end
  end

  // Halted and stalled bits padded to four engines for STATUS and ATTN_MASK.
  logic [3:0] halted4, stalled4, enable4;
  always_comb begin
    halted4  = '0;
    stalled4 = '0;
    enable4  = '0;
    halted4[NE-1:0]  = halted_i;
    stalled4[NE-1:0] = stalled_i;
    enable4[NE-1:0]  = enable_q;
  end

  assign attn_o = (|(flags_q[3:0] & attn_mask_q[3:0])) | (|(halted4 & attn_mask_q[7:4]));

  logic [7:0] glob_rd;
  always_comb begin
    case (off)
      6'h00:   glob_rd = ID_VALUE;
      6'h01:   glob_rd = VERSION_VALUE;
      6'h02:   glob_rd = {4'h0, enable4};
      6'h04:   glob_rd = flags_q;
      6'h07:   glob_rd = attn_mask_q;
      6'h08:   glob_rd = {6'h00, lock_q, attn_en_q};
      6'h09:   glob_rd = {stalled4, halted4};
      6'h10:   glob_rd = owner_out_q[7:0];
      6'h11:   glob_rd = owner_out_q[15:8];
      6'h12:   glob_rd = owner_io_q[7:0];
      6'h13:   glob_rd = owner_io_q[15:8];
      6'h14:   glob_rd = drive_out_q;
      6'h15:   glob_rd = drive_io_q;
      6'h16:   glob_rd = open_drain_q;
      default: glob_rd = 8'h00;
    endcase
  end

  // ----------------------------------------------------- engine registers
  wire [NE-1:0] we_ereg = {NE{we_i & sel_ereg}} & e_hot;

  logic [NE*8-1:0] ereg_rd;      // what each engine's block reads as at "off"

  genvar g;
  generate
    for (g = 0; g < NE; g = g + 1) begin : g_ereg
      logic [3:0]  cfg_q;        // [0] out_dir [1] in_dir [2] autopull [3] autopush
      logic        crcdir_q;     // CFG bit 4
      logic [3:0]  pull_q, push_q;
      logic [15:0] clkdiv_q;
      logic [5:0]  side0_q, side1_q;
      logic [31:0] poly_q;
      logic [5:0]  width_q;
      logic [1:0]  hdbg_q;       // [0] host wrote a full TX FIFO, [1] host read an empty RX FIFO

      wire we  = we_ereg[g];
      wire pop = rd_pop_i & sel_ereg & e_hot[g] & (off == 6'h0C);

      always_ff @(posedge clk or negedge rst_ni) begin
        if (!rst_ni) begin
          cfg_q    <= '0;
          pull_q   <= 4'd8;
          push_q   <= 4'd8;
          clkdiv_q <= '0;
          side0_q  <= '0;
          side1_q  <= '0;
          hdbg_q   <= '0;
        end else begin
          if (we) begin
            case (off)
              6'h00: cfg_q           <= wdata_i[3:0];
              6'h01: pull_q          <= wdata_i[3:0];
              6'h02: push_q          <= wdata_i[3:0];
              6'h03: clkdiv_q[7:0]   <= wdata_i;
              6'h04: clkdiv_q[15:8]  <= wdata_i;
              6'h05: side0_q         <= wdata_i[5:0];
              6'h06: side1_q         <= wdata_i[5:0];
              default: ;
            endcase
          end
          // DEBUG: write 1 to clear; an event on the same clock wins.
          if (restart_q[g])               hdbg_q <= '0;
          else begin
            if (we && off == 6'h0D)       hdbg_q <= hdbg_q & ~wdata_i[1:0];
            if (we && off == 6'h0C && tx_full_i[g]) hdbg_q[0] <= 1'b1;
            if (pop && rx_empty_i[g])     hdbg_q[1] <= 1'b1;
          end
        end
      end

      // Checksum settings exist only on an engine that has the unit; on the
      // others they read as zero.
      if (HAS_CRC[g]) begin : g_crc
        always_ff @(posedge clk or negedge rst_ni) begin
          if (!rst_ni) begin
            crcdir_q <= 1'b0;
            poly_q   <= '0;
            width_q  <= 6'd32;
          end else if (we) begin
            case (off)
              6'h00: crcdir_q        <= wdata_i[4];
              6'h0E: poly_q[7:0]     <= wdata_i;
              6'h0F: poly_q[15:8]    <= wdata_i;
              6'h10: poly_q[23:16]   <= wdata_i;
              6'h11: poly_q[31:24]   <= wdata_i;
              6'h12: width_q         <= wdata_i[5:0];
              default: ;
            endcase
          end
        end
      end else begin : g_nocrc
        assign crcdir_q = 1'b0;
        assign poly_q   = '0;
        assign width_q  = '0;
      end

      assign cfg_out_dir_o[g]            = cfg_q[0];
      assign cfg_in_dir_o[g]             = cfg_q[1];
      assign cfg_autopull_o[g]           = cfg_q[2];
      assign cfg_autopush_o[g]           = cfg_q[3];
      assign cfg_crc_dir_o[g]            = crcdir_q;
      assign cfg_pull_thresh_o[g*4 +: 4] = pull_q;
      assign cfg_push_thresh_o[g*4 +: 4] = push_q;
      assign cfg_clkdiv_o[g*16 +: 16]    = clkdiv_q;
      assign cfg_side0_o[g*6 +: 6]       = side0_q;
      assign cfg_side1_o[g*6 +: 6]       = side1_q;
      assign cfg_crc_poly_o[g*32 +: 32]  = poly_q;
      assign cfg_crc_width_o[g*6 +: 6]   = width_q;

      // Writes with a side effect in the engine.
      assign pc_we_o[g]          = we & (off == 6'h07 || off == 6'h08) & ~enable_q[g];
      assign tx_push_o[g]        = we & (off == 6'h0C);
      assign rx_pop_o[g]         = pop;
      assign dbg_clr_o[g*2 +: 2] = (we && off == 6'h0D) ? wdata_i[3:2] : 2'b00;
      assign hreg_we_o[g]        = we & (off[5:4] == 2'b10) & ~enable_q[g];

      wire [15:0] r_val   = HOST_RB ? hreg_rdata_i[g*16 +: 16] : 16'h0000;
      wire [31:0] crc_val = crc_i[g*32 +: 32];

      logic [7:0] rd;
      always_comb begin
        case (off)
          6'h00:   rd = {3'b000, crcdir_q, cfg_q};
          6'h01:   rd = {4'h0, pull_q};
          6'h02:   rd = {4'h0, push_q};
          6'h03:   rd = clkdiv_q[7:0];
          6'h04:   rd = clkdiv_q[15:8];
          6'h05:   rd = {2'b00, side0_q};
          6'h06:   rd = {2'b00, side1_q};
          6'h07:   rd = pc_i[g*9 +: 8];
          6'h08:   rd = {7'd0, pc_i[g*9 + 8]};
          6'h09:   rd = {rx_full_i[g], rx_empty_i[g], tx_full_i[g], tx_empty_i[g],
                         illegal_i[g], halted_i[g], stalled_i[g],
                         enable_q[g] & ~halted_i[g]};
          6'h0A:   rd = {3'b000, tx_level_i[g*5 +: 5]};
          6'h0B:   rd = {3'b000, rx_level_i[g*5 +: 5]};
          6'h0C:   rd = rx_data_i[g*8 +: 8];
          6'h0D:   rd = {4'h0, debug_i[g*2 +: 2], hdbg_q};
          6'h0E:   rd = poly_q[7:0];
          6'h0F:   rd = poly_q[15:8];
          6'h10:   rd = poly_q[23:16];
          6'h11:   rd = poly_q[31:24];
          6'h12:   rd = {2'b00, width_q};
          6'h13:   rd = size_i[g*12 +: 8];
          6'h18:   rd = {4'd0, size_i[g*12 + 8 +: 4]};
          6'h19:   rd = {6'd0, feat_i[g*2 +: 2]};
          6'h14:   rd = crc_val[7:0];
          6'h15:   rd = crc_val[15:8];
          6'h16:   rd = crc_val[23:16];
          6'h17:   rd = crc_val[31:24];
          default: begin
            // 0x20..0x2F: r0..r7, two bytes each, lowest byte first.
            if (off[5:4] == 2'b10) rd = off[0] ? r_val[15:8] : r_val[7:0];
            else                   rd = 8'h00;
          end
        endcase
      end
      assign ereg_rd[g*8 +: 8] = rd;
    end
  endgenerate

  // The host writes the program counter one byte at a time and keeps the
  // other part.
  logic [8:0] pc_sel;
  integer     m;
  always_comb begin
    pc_sel = '0;
    for (m = 0; m < NE; m = m + 1) begin
      if (e_hot[m]) pc_sel = pc_i[m*9 +: 9];
    end
  end
  assign pc_wdata_o = (off == 6'h07) ? {pc_sel[8], wdata_i} : {wdata_i[0], pc_sel[7:0]};
  assign tx_data_o  = wdata_i;

  // ------------------------------------------- per-engine values at "e"
  // Selected with an AND-OR so that an engine number above NE-1 reads zero.
  logic [7:0]  ereg_sel, dmem_sel;
  logic [31:0] prog_sel;
  logic        run_sel;
  integer      j;
  always_comb begin
    ereg_sel = '0;
    dmem_sel = '0;
    prog_sel = '0;
    run_sel  = 1'b0;
    for (j = 0; j < NE; j = j + 1) begin
      if (e_hot[j]) begin
        ereg_sel = ereg_rd[j*8 +: 8];
        dmem_sel = HOST_RB ? dm_rdata_i[j*8 +: 8] : 8'h00;
        prog_sel = prog_rdata_i[j*32 +: 32];
        run_sel  = enable_q[j];
      end
    end
  end

  // -------------------------------------------------- registers r0..r7
  // The engine stores 16-bit values; the host writes one byte of one.
  assign hreg_sel_o   = off[3:1];
  assign hreg_hi_o    = off[0];
  assign hreg_wdata_o = wdata_i;

  // ---------------------------------------------------------- data memory
  assign dm_addr_o  = addr_i[3:0];
  assign dm_wdata_o = wdata_i;
  assign dm_we_o    = {NE{we_i & sel_dmem}} & e_hot;

  // ------------------------------------------------------- program memory
  // A word is four bytes, lowest first. The first three are kept here and
  // the word is stored when the fourth arrives. The host reaches a program
  // memory only while its engine is stopped (ENABLE bit clear).
  logic [23:0] wbuf_q;
  wire         we_prog = we_i & sel_prog;

  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      wbuf_q <= '0;
    end else if (we_prog) begin
      case (addr_i[1:0])
        2'd0:    wbuf_q[7:0]   <= wdata_i;
        2'd1:    wbuf_q[15:8]  <= wdata_i;
        2'd2:    wbuf_q[23:16] <= wdata_i;
        default: ;
      endcase
    end
  end

  assign prog_addr_o  = addr_i[10:2];
  assign prog_wdata_o = {wdata_i, wbuf_q};
  assign prog_we_o    = {NE{we_prog & (addr_i[1:0] == 2'd3)}} & e_hot & ~enable_q;
  assign prog_re_o    = {NE{reading_i & sel_prog}} & e_hot & ~enable_q;

  logic [7:0] prog_rd;
  always_comb begin
    case (addr_i[1:0])
      2'd0:    prog_rd = prog_sel[7:0];
      2'd1:    prog_rd = prog_sel[15:8];
      2'd2:    prog_rd = prog_sel[23:16];
      default: prog_rd = prog_sel[31:24];
    endcase
    if (run_sel) prog_rd = 8'h00;
  end

  // ------------------------------------------------------------ read data
  always_comb begin
    if (sel_glob)      rdata_o = glob_rd;
    else if (sel_ereg) rdata_o = ereg_sel;
    else if (sel_dmem) rdata_o = dmem_sel;
    else if (sel_prog) rdata_o = prog_rd;
    else               rdata_o = 8'h00;
  end

  // -------------------------------------------------------------- outputs
  assign enable_o     = enable_q;
  assign restart_o    = restart_q;
  assign flags_o      = flags_q;
  assign owner_out_o  = owner_out_q;
  assign owner_io_o   = owner_io_q;
  assign drive_out_o  = drive_out_q;
  assign drive_io_o   = drive_io_q;
  assign open_drain_o = open_drain_q;
  assign attn_en_o    = attn_en_q;
  assign lock_o       = lock_q;

endmodule

`default_nettype wire
