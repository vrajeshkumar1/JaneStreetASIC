// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: Apache-2.0
//
// PYNQ-Z2 (TUL, Zynq XC7Z020) wrapper: the Tiny Tapeout design on the FPGA
// fabric at the chip's clock, with its 24 pins on the board's headers, so the
// programs and the host software can be tried on real wires before the chip
// exists.
//
// Clock:  125 MHz on H16 -> MMCM -> 60 MHz (VCO 750 MHz, divide 12.5).
// Reset:  BTN0 (pressed = reset), held until the MMCM has locked.
// Pins:   ui_in[7:0]  <- Pmod A (JA1..JA4, JA7..JA10)
//         uo_out[7:0] -> Pmod B (JB1..JB4, JB7..JB10)
//         uio[7:0]   <-> Arduino AR0..AR7 (each through the board's 200 ohm resistor)
//         LED0 = MMCM locked, LED1 = reset held, LED2 = host select low
//         (ui_in[0]), LED3 = uo_out[0].
// Pmod pin n of each header carries bit n-1 for pins 1..4 and bit n-3 for
// pins 7..10, the order Tiny Tapeout's demo board uses.

`default_nettype none

module pynq_z2_top (
    input  wire       sysclk,
    input  wire       btn0,
    input  wire [7:0] ja,
    output wire [7:0] jb,
    inout  wire [7:0] ar,
    output wire [3:0] led
);

  // ---- 60 MHz from 125 MHz
  wire clk_fb, clk60_mmcm, clk60, locked;
  MMCME2_BASE #(
      .CLKIN1_PERIOD   (8.000),
      .DIVCLK_DIVIDE   (1),
      .CLKFBOUT_MULT_F (6.000),
      .CLKOUT0_DIVIDE_F(12.500)
  ) u_mmcm (
      .CLKIN1   (sysclk),
      .CLKFBIN  (clk_fb),
      .CLKFBOUT (clk_fb),
      .CLKOUT0  (clk60_mmcm),
      .LOCKED   (locked),
      .PWRDWN   (1'b0),
      .RST      (1'b0),
      .CLKFBOUTB(),
      .CLKOUT0B (),
      .CLKOUT1  (),
      .CLKOUT1B (),
      .CLKOUT2  (),
      .CLKOUT2B (),
      .CLKOUT3  (),
      .CLKOUT3B (),
      .CLKOUT4  (),
      .CLKOUT5  (),
      .CLKOUT6  ()
  );
  BUFG u_bufg (.I(clk60_mmcm), .O(clk60));

  // ---- reset: asserted at once, released two clocks after BTN0 and lock
  reg [1:0] rst_sync;
  wire rst_req = btn0 | ~locked;
  always @(posedge clk60 or posedge rst_req) begin
    if (rst_req) rst_sync <= 2'b00;
    else         rst_sync <= {rst_sync[0], 1'b1};
  end
  wire rst_n = rst_sync[1];

  // ---- the design
  wire [7:0] uo_out, uio_out, uio_oe;
  tt_um_vrajeshkumar1_janestreetasic u_design (
      .ui_in  (ja),
      .uo_out (uo_out),
      .uio_in (ar),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (1'b1),
      .clk    (clk60),
      .rst_n  (rst_n)
  );

  assign jb = uo_out;
  genvar g;
  generate
    for (g = 0; g < 8; g = g + 1) begin : g_uio
      assign ar[g] = uio_oe[g] ? uio_out[g] : 1'bz;
    end
  endgenerate

  assign led = {uo_out[0], ~ja[0], ~rst_n, locked};

endmodule

`default_nettype wire
