`default_nettype none
`timescale 1ns / 1ps

/* Test bench for the whole chip: the Tiny Tapeout top-level module and the
   wires outside it. The cocotb tests in test.py drive ui_in and io_ext and
   read uo_out and io_line; they reach the design only through its pins, so
   the same tests run on the gate-level netlist.

   Each bidirectional pin is modelled as a wire with something outside the
   chip on it: when the chip drives the pin (uio_oe = 1) the wire carries
   uio_out, otherwise it carries io_ext (1 = pulled up or driven high by the
   outside, 0 = held low by the outside).

   Derived from the Tiny Tapeout template (Apache-2.0); see NOTICE.md.
*/
module tb ();

  // Dump the signals to a FST file. You can view it with gtkwave or surfer.
  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  // Wire up the inputs and outputs:
  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] io_ext;
  wire [7:0] io_line;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  genvar g;
  generate
    for (g = 0; g < 8; g = g + 1) begin : g_io
      assign io_line[g] = uio_oe[g] ? uio_out[g] : io_ext[g];
    end
  endgenerate

  tt_um_vrajeshkumar1_janestreetasic user_project (
      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (io_line),  // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

endmodule
