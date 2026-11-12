// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// Everything between the tile's pins and the engines (docs/spec.md, sections
// 2.1 and 3):
//   - two flip-flops on every input pin, because the pins are not timed to
//     the chip clock
//   - the host link's three borrowed pins: while host select (ui_in[0]) is
//     low, ui_in[1] is the SPI clock, ui_in[2] is SPI data in and uo_out[0]
//     is SPI data out. The engines see in1 and in2 frozen during that time
//   - pin sharing: each writable pin has one owning engine, chosen by the
//     host, and a drive enable
//   - one flip-flop on every output, so that all pins change at the same
//     delay after the clock edge whichever engine drives them
//
// Per-engine buses are flat vectors: engine e uses bits [e*W +: W].
//
// Naming: *_q is a flip-flop output, *_i / *_o are ports.

`default_nettype none

module pe_pins #(
    parameter int unsigned NE = 4          // number of engines, 1..4
) (
    input  wire             clk,
    input  wire             rst_ni,

    // ---- tile pins
    input  wire [7:0]       ui_in,
    output wire [7:0]       uo_out,
    input  wire [7:0]       uio_in,
    output wire [7:0]       uio_out,
    output wire [7:0]       uio_oe,        // 1 = output

    // ---- host link
    input  wire             lock_i,        // ignore host select
    output wire             host_active_o,
    output wire             sck_o,
    output wire             mosi_o,
    input  wire             miso_i,
    input  wire             attn_en_i,     // out0 is the attention line
    input  wire             attn_i,

    // ---- pin settings
    input  wire [15:0]      owner_out_i,   // two bits per output pin
    input  wire [15:0]      owner_io_i,    // two bits per bidirectional pin
    input  wire [7:0]       drive_out_i,
    input  wire [7:0]       drive_io_i,
    input  wire [7:0]       open_drain_i,

    // ---- engines
    output wire [15:0]      pins_o,        // [7:0] input pins, [15:8] bidirectional pins
    input  wire [NE*16-1:0] level_i,       // per engine: [7:0] output pins, [15:8] bidirectional pins
    input  wire [NE*8-1:0]  dir_i          // per engine: bidirectional pins, 1 = output
);

  // ---------------------------------------------------------- input side
  // Host select resets to 1 (not selected); the others reset to 0.
  logic [7:0] ui_meta_q, ui_sync_q;
  logic [7:0] uio_meta_q, uio_sync_q;
  logic [1:0] frozen_q;                    // in2, in1 as the engines last saw them

  wire host_active = ~ui_sync_q[0] & ~lock_i;

  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      ui_meta_q  <= 8'h01;
      ui_sync_q  <= 8'h01;
      uio_meta_q <= '0;
      uio_sync_q <= '0;
      frozen_q   <= '0;
    end else begin
      ui_meta_q  <= ui_in;
      ui_sync_q  <= ui_meta_q;
      uio_meta_q <= uio_in;
      uio_sync_q <= uio_meta_q;
      if (!host_active) frozen_q <= ui_sync_q[2:1];
    end
  end

  assign host_active_o = host_active;
  assign sck_o         = ui_sync_q[1];
  assign mosi_o        = ui_sync_q[2];

  assign pins_o = {uio_sync_q,
                   ui_sync_q[7:3],
                   host_active ? frozen_q : ui_sync_q[2:1],
                   ui_sync_q[0]};

  // --------------------------------------------------------- output side
  // Engine buses padded to four entries, so that an owner number above
  // NE-1 reads as "level 0, input".
  logic [63:0] level4;
  logic [31:0] dir4;
  always_comb begin
    level4 = '0;
    dir4   = '0;
    level4[NE*16-1:0] = level_i;
    dir4[NE*8-1:0]    = dir_i;
  end

  logic [7:0] uo_d, uio_out_d, uio_oe_d;
  logic [1:0] own;
  logic       lvl;
  integer     n;
  always_comb begin
    own = 2'd0;
    lvl = 1'b0;
    for (n = 0; n < 8; n = n + 1) begin
      // Output pin n.
      own     = owner_out_i[n*2 +: 2];
      lvl     = level4[own*16 + n];
      uo_d[n] = drive_out_i[n] & lvl;

      // Bidirectional pin n. An open-drain pin is never driven high: level 1
      // releases it and level 0 drives it low, whatever its direction bit.
      own = owner_io_i[n*2 +: 2];
      lvl = level4[own*16 + 8 + n];
      if (!drive_io_i[n]) begin
        uio_oe_d[n]  = 1'b0;
        uio_out_d[n] = 1'b0;
      end else if (open_drain_i[n]) begin
        uio_oe_d[n]  = ~lvl;
        uio_out_d[n] = 1'b0;
      end else begin
        uio_oe_d[n]  = dir4[own*8 + n];
        uio_out_d[n] = lvl;
      end
    end

    // out0 carries host data while the host has the chip selected, and can
    // be the attention line the rest of the time.
    if (host_active)    uo_d[0] = miso_i;
    else if (attn_en_i) uo_d[0] = attn_i;
  end

  logic [7:0] uo_q, uio_out_q, uio_oe_q;
  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      uo_q      <= '0;
      uio_out_q <= '0;
      uio_oe_q  <= '0;
    end else begin
      uo_q      <= uo_d;
      uio_out_q <= uio_out_d;
      uio_oe_q  <= uio_oe_d;
    end
  end

  assign uo_out  = uo_q;
  assign uio_out = uio_out_q;
  assign uio_oe  = uio_oe_q;

endmodule

`default_nettype wire
