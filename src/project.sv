// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// PROBE BUILD. This is not the protocol emulator yet. It is a small design that
// answers four questions about the Tiny Tapeout CMOS5L flow before the real
// core is written:
//   1. Does the flow accept an 8x4 tile with one IHP 256x32 memory block?
//   2. Which SystemVerilog constructs do the synthesis parser and the
//      simulator both accept? (This file uses the ones the core will use.)
//   3. Do the power stripes land on the memory block's supply columns?
//   4. How much time is left in the loop "memory output -> decode -> next
//      address -> memory address" at 60 MHz? That loop is the one the engine's
//      zero-penalty branch depends on. RUN mode below reproduces it.
//
// Pin use in the probe:
//   ui_in[7:0]   data byte
//   uio_in[2:0]  command (see cmd_t), sampled every clock
//   uo_out[7:0]  selected byte of the last word read, or the program counter
//                while RUN is held
//   uio_out/oe   unused (all inputs)

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

  typedef enum logic [2:0] {
    CMD_IDLE  = 3'd0,
    CMD_ADDR  = 3'd1,  // address <- ui_in
    CMD_SHIFT = 3'd2,  // write word <- {write word[23:0], ui_in}
    CMD_WRITE = 3'd3,  // memory[address] <- write word
    CMD_READ  = 3'd4,  // read word <- memory[address] (valid two clocks later)
    CMD_SEL   = 3'd5,  // byte select <- ui_in[1:0]
    CMD_RUN   = 3'd6   // follow the words in memory as a tiny program
  } cmd_t;

  // ---------------------------------------------------------------- reset
  // Asynchronous assert, synchronous release.
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

  // ------------------------------------------------- input synchronizers
  logic [7:0] ui_meta_q, ui_q;
  logic [2:0] cmd_meta_q, cmd_q;
  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      ui_meta_q  <= '0;
      ui_q       <= '0;
      cmd_meta_q <= '0;
      cmd_q      <= '0;
    end else begin
      ui_meta_q  <= ui_in;
      ui_q       <= ui_meta_q;
      cmd_meta_q <= uio_in[2:0];
      cmd_q      <= cmd_meta_q;
    end
  end

  cmd_t cmd;
  always_comb cmd = cmd_t'(cmd_q);

  // -------------------------------------------------------------- state
  logic [7:0]  addr_q;
  logic [31:0] wdata_q;
  logic [1:0]  sel_q;
  logic        rd_pending_q;
  logic [31:0] rdata_q;
  logic [7:0]  pc_q;
  logic        run_valid_q;   // mem_dout holds the word at pc_q
  logic        t_q;           // stand-in for the engine's T flag
  logic [7:0]  out_q;

  logic        mem_en, mem_we, mem_re;
  logic [7:0]  mem_addr;
  logic [31:0] mem_dout;

  // The loop under test: decode the word that just came out of the memory and
  // choose the next address in the same clock period.
  logic       is_jump, cond_ok, take;
  logic [7:0] next_pc;
  always_comb begin
    is_jump = (mem_dout[31:28] == 4'd0);
    cond_ok = (mem_dout[27:26] == 2'b00) || (mem_dout[27] ^ t_q);
    take    = is_jump && cond_ok;
    next_pc = take ? mem_dout[7:0] : (pc_q + 8'd1);
  end

  always_comb begin
    mem_en   = 1'b0;
    mem_we   = 1'b0;
    mem_re   = 1'b0;
    mem_addr = addr_q;
    case (cmd)
      CMD_WRITE: begin
        mem_en = 1'b1;
        mem_we = 1'b1;
      end
      CMD_READ: begin
        mem_en = 1'b1;
        mem_re = 1'b1;
      end
      CMD_RUN: begin
        mem_en   = 1'b1;
        mem_re   = 1'b1;
        mem_addr = run_valid_q ? next_pc : addr_q;
      end
      default: ;
    endcase
  end

  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      addr_q       <= '0;
      wdata_q      <= '0;
      sel_q        <= '0;
      rd_pending_q <= 1'b0;
      rdata_q      <= '0;
      pc_q         <= '0;
      run_valid_q  <= 1'b0;
      t_q          <= 1'b0;
      out_q        <= '0;
    end else begin
      rd_pending_q <= (cmd == CMD_READ);
      if (rd_pending_q) rdata_q <= mem_dout;

      case (cmd)
        CMD_ADDR:  addr_q  <= ui_q;
        CMD_SHIFT: wdata_q <= {wdata_q[23:0], ui_q};
        CMD_SEL:   sel_q   <= ui_q[1:0];
        default: ;
      endcase

      if (cmd == CMD_RUN) begin
        run_valid_q <= 1'b1;
        pc_q        <= mem_addr;
        if (run_valid_q) t_q <= mem_dout[0];
      end else begin
        run_valid_q <= 1'b0;
      end

      if (cmd == CMD_RUN) begin
        out_q <= pc_q;
      end else begin
        case (sel_q)
          2'd0: out_q <= rdata_q[7:0];
          2'd1: out_q <= rdata_q[15:8];
          2'd2: out_q <= rdata_q[23:16];
          default: out_q <= rdata_q[31:24];
        endcase
      end
    end
  end

  // ------------------------------------------------------- memory block
  // IHP single-port 256 x 32. A_DLY must be 1 (datasheet); self-test port off.
  RM_IHPSG13_1P_256x32_c2_bm_bist u_mem (
      .A_CLK      (clk),
      .A_MEN      (mem_en),
      .A_WEN      (mem_we),
      .A_REN      (mem_re),
      .A_ADDR     (mem_addr),
      .A_DIN      (wdata_q),
      .A_DLY      (1'b1),
      .A_DOUT     (mem_dout),
      .A_BM       (32'hFFFF_FFFF),
      .A_BIST_CLK (1'b0),
      .A_BIST_EN  (1'b0),
      .A_BIST_MEN (1'b0),
      .A_BIST_WEN (1'b0),
      .A_BIST_REN (1'b0),
      .A_BIST_ADDR(8'h00),
      .A_BIST_DIN (32'h0000_0000),
      .A_BIST_BM  (32'h0000_0000)
  );

  assign uo_out  = out_q;
  assign uio_out = 8'h00;
  assign uio_oe  = 8'h00;

  wire _unused = &{ena, uio_in[7:3], 1'b0};

endmodule

`default_nettype wire
