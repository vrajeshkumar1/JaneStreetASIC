// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// Byte FIFO. Depth is 2**AW entries. The bytes are kept in latches (pe_lmem
// below); the pointers and the level are flip-flops.
// The oldest byte is always visible on rdata_o (no read delay).
// A push and a pop on the same clock are both carried out.

// This file also holds pe_lmem, the latch storage used by the FIFOs and by the
// data memory of an engine, and pe_clkgate, the clock gate it is built on.

`default_nettype none

// ---------------------------------------------------------------- clock gate
// gclk_o is clk while the enable is 1 and low otherwise. The enable is taken
// while clk is low and held while it is high, so gclk_o is always a whole
// high phase of clk and a change of en_i after the rising edge has no effect
// until the next one.
//
// In the layout flow (PE_USE_LIB_CELLS, set in src/config.json) this is the
// library's clock-gate cell, which the clock-tree step knows how to handle.
// Without the definition it is the same thing written out, for simulation.
module pe_clkgate (
    input  wire clk,
    input  wire en_i,
    output wire gclk_o
);
`ifdef PE_USE_LIB_CELLS
  sg13cmos5l_lgcp_1 u_cg (.CLK(clk), .GATE(en_i), .GCLK(gclk_o));
`else
  logic en_l;
  /* verilator lint_off LATCH */
  always_latch if (!clk) en_l = en_i;
  /* verilator lint_on LATCH */
  assign gclk_o = clk & en_l;
`endif
endmodule

// ------------------------------------------------------------ latch storage
// 2**AW bytes, one write port. Seen from outside it behaves like an array of
// flip-flops with a write enable: a byte written on one clock edge reads back
// with its new value after that edge.
//
// How a write is carried out:
//   - the byte to store is captured in a flip-flop (wdata_q) on the clock
//     edge of the write;
//   - on that same edge the clock gate of the addressed byte lets one high
//     phase of the clock through to the latches of that byte;
//   - the latches follow wdata_q during that high phase and hold when the
//     clock falls. wdata_q cannot change before the next rising edge, so the
//     latches close half a clock before their input moves.
// Nothing but a flip-flop output drives a latch input and nothing but a
// clock-gate cell drives a latch enable, so a glitch in the logic in front
// cannot be stored.
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

  localparam int unsigned DEPTH = 1 << AW;

  logic [7:0] wdata_q;
  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) wdata_q <= '0;
    else         wdata_q <= wdata_i;
  end

  genvar b;
  generate
    for (b = 0; b < DEPTH; b = b + 1) begin : g_byte
      wire        gclk;
      logic [7:0] l;
      pe_clkgate u_gate (.clk(clk), .en_i(we_i & (waddr_i == b[AW-1:0])), .gclk_o(gclk));
      /* verilator lint_off LATCH */
      always_latch begin
        if (!rst_ni)   l = 8'h00;
        else if (gclk) l = wdata_q;
      end
      /* verilator lint_on LATCH */
      assign q_o[b*8 +: 8] = l;
    end
  endgenerate

endmodule

// ---------------------------------------------------------------------- FIFO
module pe_fifo #(
    parameter int unsigned AW = 4
) (
    input  wire          clk,
    input  wire          rst_ni,
    input  wire          clear_i,   // empty the FIFO
    input  wire          push_i,
    input  wire  [7:0]   wdata_i,
    input  wire          pop_i,
    output wire  [7:0]   rdata_o,
    output wire          empty_o,
    output wire          full_o,
    output wire  [AW:0]  level_o
);

  localparam int unsigned DEPTH = 1 << AW;

  wire  [DEPTH*8-1:0] mem_q;
  logic [AW-1:0]      wptr_q, rptr_q;
  logic [AW:0]        level_q;

  wire do_push = push_i & ~full_o;
  wire do_pop  = pop_i & ~empty_o;

  assign empty_o = (level_q == '0);
  assign full_o  = level_q[AW];
  assign level_o = level_q;
  assign rdata_o = mem_q[rptr_q*8 +: 8];

  pe_lmem #(.AW(AW)) u_mem (
      .clk(clk), .rst_ni(rst_ni),
      .we_i(do_push & ~clear_i), .waddr_i(wptr_q), .wdata_i(wdata_i), .q_o(mem_q)
  );

  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      wptr_q  <= '0;
      rptr_q  <= '0;
      level_q <= '0;
    end else if (clear_i) begin
      wptr_q  <= '0;
      rptr_q  <= '0;
      level_q <= '0;
    end else begin
      if (do_push) begin
        wptr_q <= wptr_q + 1'b1;
      end
      if (do_pop) rptr_q <= rptr_q + 1'b1;
      if (do_push && !do_pop) level_q <= level_q + 1'b1;
      if (do_pop && !do_push) level_q <= level_q - 1'b1;
    end
  end

endmodule

`default_nettype wire
