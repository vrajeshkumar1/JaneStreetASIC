// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// Byte FIFO built from flip-flops. Depth is 2**AW entries.
// The oldest byte is always visible on rdata_o (no read delay).
// A push and a pop on the same clock are both carried out.

`default_nettype none

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

  logic [DEPTH*8-1:0] mem_q;
  logic [AW-1:0]      wptr_q, rptr_q;
  logic [AW:0]        level_q;

  wire do_push = push_i & ~full_o;
  wire do_pop  = pop_i & ~empty_o;

  assign empty_o = (level_q == '0);
  assign full_o  = level_q[AW];
  assign level_o = level_q;
  assign rdata_o = mem_q[rptr_q*8 +: 8];

  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      mem_q   <= '0;
      wptr_q  <= '0;
      rptr_q  <= '0;
      level_q <= '0;
    end else if (clear_i) begin
      wptr_q  <= '0;
      rptr_q  <= '0;
      level_q <= '0;
    end else begin
      if (do_push) begin
        mem_q[wptr_q*8 +: 8] <= wdata_i;
        wptr_q <= wptr_q + 1'b1;
      end
      if (do_pop) rptr_q <= rptr_q + 1'b1;
      if (do_push && !do_pop) level_q <= level_q + 1'b1;
      if (do_pop && !do_push) level_q <= level_q - 1'b1;
    end
  end

endmodule

`default_nettype wire
