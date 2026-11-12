// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// Host link: SPI target, mode 0, highest bit first (docs/spec.md, part 2).
//
// The SPI clock is not used as a clock. It is sampled with the chip clock and
// its rising edges are detected, so everything here is in one clock domain.
// The three pins arrive already synchronized (pe_pins.sv).
//
// Transfer format:
//   write:  [1 a14..a8] [a7..a0] [data] [data] ...
//   read:   [0 a14..a8] [a7..a0] [dummy] [data] [data] ...
//
// The module turns a transfer into single-byte reads and writes on a small
// bus: addr_o, we_o + wdata_o for writes, rdata_i for reads.
//
// Data out to the host changes after a detected rising edge, not after the
// falling edge. The host has already sampled the old bit on that rising edge,
// and the new bit then has a whole SPI clock period to reach the host instead
// of half of one. For a read, addr_o is always the address of the byte that
// will be loaded next: it is loaded into the shift register on the last
// rising edge of the byte before it.
//
// A FIFO address is read without removing anything. The byte is removed only
// when the host has clocked out all eight bits of it (rd_pop_o), and the next
// byte is loaded one clock later. A transfer that stops part-way through a
// byte, or a stray clock edge at the end of a transfer, therefore loses
// nothing.
//
// Naming: *_q is a flip-flop output, *_i / *_o are ports.

`default_nettype none

module pe_spi (
    input  wire        clk,
    input  wire        rst_ni,

    // ---- pins, synchronized to clk
    input  wire        active_i,   // 1 = the host has selected the chip
    input  wire        sck_i,
    input  wire        mosi_i,
    output wire        miso_o,

    // ---- byte bus
    output wire [14:0] addr_o,
    output wire        we_o,       // one clock: store wdata_o at addr_o
    output wire [7:0]  wdata_o,
    output wire        reading_o,  // a read transfer is in progress
    input  wire [7:0]  rdata_i,    // contents of addr_o
    input  wire        hold_i,     // addr_o is a FIFO: it does not advance
    output wire        rd_pop_o    // one clock: the host has taken all of the
                                   // FIFO byte that was loaded from addr_o
);

  localparam logic [1:0] PH_CMD   = 2'd0;   // first byte: read/write, a14..a8
  localparam logic [1:0] PH_ADDR  = 2'd1;   // second byte: a7..a0
  localparam logic [1:0] PH_DUMMY = 2'd2;   // read only: one byte to fetch data
  localparam logic [1:0] PH_DATA  = 2'd3;

  logic        sck_q;       // sck_i one clock ago; held at 1 while not selected
  logic [2:0]  bit_q;       // bits received in the current byte
  logic [6:0]  sh_q;        // bits received so far
  logic [1:0]  ph_q;
  logic        rw_q;        // 1 = write
  logic [14:0] addr_q;
  logic [7:0]  tx_q;        // byte going out, highest bit at tx_q[7]
  logic        held_q;      // tx_q was loaded from a FIFO address
  logic        reload_q;    // load tx_q from the FIFO on this clock

  wire       rise     = active_i & sck_i & ~sck_q;
  wire [7:0] rx_byte  = {sh_q, mosi_i};
  wire       byte_end = rise & (bit_q == 3'd7);
  wire       rd_data  = (ph_q == PH_DATA) & ~rw_q;

  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      sck_q    <= 1'b1;
      bit_q    <= '0;
      sh_q     <= '0;
      ph_q     <= PH_CMD;
      rw_q     <= 1'b0;
      addr_q   <= '0;
      tx_q     <= '0;
      held_q   <= 1'b0;
      reload_q <= 1'b0;
    end else begin
      // A rising edge counts only if the clock was seen low while the chip
      // was selected. Holding sck_q at 1 until then means a clock pin that is
      // high, or that goes high at the same moment host select goes low, is
      // not taken for an edge.
      sck_q    <= active_i ? sck_i : 1'b1;
      reload_q <= 1'b0;
      if (!active_i) begin
        // Host select is high: forget any transfer in progress.
        bit_q  <= '0;
        ph_q   <= PH_CMD;
        rw_q   <= 1'b0;
        tx_q   <= '0;
        held_q <= 1'b0;
      end else if (rise) begin
        bit_q <= bit_q + 3'd1;
        sh_q  <= rx_byte[6:0];
        if (byte_end) begin
          case (ph_q)
            PH_CMD: begin
              rw_q         <= rx_byte[7];
              addr_q[14:8] <= rx_byte[6:0];
              ph_q         <= PH_ADDR;
            end
            PH_ADDR: begin
              addr_q[7:0] <= rx_byte;
              ph_q        <= rw_q ? PH_DATA : PH_DUMMY;
            end
            default: begin
              // End of the dummy byte or of a data byte.
              ph_q <= PH_DATA;
              if (!rw_q) begin
                if (held_q) reload_q <= 1'b1;   // FIFO byte finished: see above
                else        tx_q     <= rdata_i;
                held_q <= hold_i;
              end
              if (!hold_i) addr_q <= addr_q + 15'd1;
            end
          endcase
        end else if (rd_data) begin
          tx_q <= {tx_q[6:0], 1'b0};
        end
      end
      // The clock after a FIFO byte was removed: the FIFO now shows the next
      // byte.
      if (active_i && reload_q) tx_q <= rdata_i;
    end
  end

  assign miso_o    = tx_q[7];
  assign addr_o    = addr_q;
  assign we_o      = byte_end & (ph_q == PH_DATA) & rw_q;
  assign wdata_o   = rx_byte;
  assign reading_o = active_i & ~rw_q & (ph_q == PH_DUMMY || ph_q == PH_DATA);
  assign rd_pop_o  = byte_end & rd_data & held_q;

endmodule

`default_nettype wire
